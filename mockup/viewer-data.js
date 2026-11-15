// Resolve benchmark and custom sky positions live from the SPHEREx IRSA ingestion API.
(() => {
  "use strict";

  const BENCHMARK_ID = {
    barnard: "barnards_star",
    epsindib: "epsilon_indi_b",
    wise0855: "wise_0855_0714",
    rwaur: "rw_aurigae",
    rdra: "r_draconis",
  };

  const loopback = new Set(["localhost", "127.0.0.1", "[::1]"]);
  const local = location.protocol === "http:" && loopback.has(location.hostname);
  const fetchData = (url, signal, timeout = 10000, options = {}) => fetch(url, {
    ...options,
    signal: AbortSignal.any([signal, AbortSignal.timeout(timeout)]),
    redirect: "error",
  });
  const waitMs = (ms, signal) => new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });

  function liveDisabledError() {
    const error = new Error("Live IRSA queries are disabled.");
    error.code = "live_disabled";
    return error;
  }

  async function readConfig(signal) {
    const response = await fetchData("viewer-config.json", signal);
    if (!response.ok) return { liveQueries: false, baseHref: "" };
    const { liveQueries, apiBaseUrl } = await response.json();
    if (liveQueries !== true) return { liveQueries: false, baseHref: "" };

    const base = new URL(apiBaseUrl || location.origin, location.origin);
    const allowedProtocol = base.protocol === "https:"
      || (base.protocol === "http:" && loopback.has(base.hostname));
    if (!allowedProtocol) {
      throw new Error("Disallowed API protocol");
    }
    return {
      liveQueries: true,
      baseHref: base.href.replace(/\/?$/, "/"),
    };
  }

  async function parseBundleResponse(result) {
    if (result.status === 404 || result.status === 204) return { status: "no-observations" };
    if (!result.ok) {
      const { detail } = await result.json().catch(() => ({}));
      const noObservations = detail?.code === "no_observations"
        || (result.status === 400 && typeof detail === "string"
          && detail.startsWith("No SPHEREx Level 2b cutouts found for target"));
      return { status: noObservations ? "no-observations" : "unavailable" };
    }
    const bundle = await result.json();
    if (!Array.isArray(bundle.frames_chronological)) return { status: "unavailable" };
    return bundle.frames_chronological.length ? { status: "ready", bundle } : { status: "no-observations" };
  }

  // onProgress hears each phase the server reports: submitting, queued, running, result.
  async function runAsyncJob(baseHref, payload, fallbackFn, signal, onProgress = () => {}) {
    onProgress({ phase: "submitting" });
    const jobResp = await fetchData(
      new URL("api/v1/jobs", baseHref),
      signal,
      30000,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (jobResp.status === 404 || jobResp.status === 405) {
      onProgress({ phase: "running" });
      return fallbackFn();
    }
    if (jobResp.status === 422) {
      const { detail } = await jobResp.json().catch(() => ({}));
      return { status: detail?.code === "no_observations" ? "no-observations" : "unavailable" };
    }
    if (!jobResp.ok) return { status: "unavailable" };

    let job = await jobResp.json();
    onProgress({ phase: job.status, cached: job.cached === true });
    const pollIntervalMs = local ? 150 : 1500;
    while (job.status === "queued" || job.status === "running") {
      if (!job.job_id) return { status: "unavailable" };
      await waitMs(pollIntervalMs, signal);
      const pollResp = await fetchData(
        new URL(`api/v1/jobs/${encodeURIComponent(job.job_id)}`, baseHref),
        signal,
        15000,
      );
      if (!pollResp.ok) return { status: "unavailable" };
      job = await pollResp.json();
      onProgress({ phase: job.status });
    }

    if (job.status === "succeeded") {
      onProgress({ phase: "result" });
      let bundle = job.result && Array.isArray(job.result.frames_chronological) ? job.result : null;
      if (!bundle) {
        if (!job.job_id) return { status: "unavailable" };
        const resultResp = await fetchData(
          new URL(`api/v1/jobs/${encodeURIComponent(job.job_id)}/result`, baseHref),
          signal,
          30000,
        );
        if (resultResp.status === 422) {
          const { detail } = await resultResp.json().catch(() => ({}));
          return { status: detail?.code === "no_observations" ? "no-observations" : "unavailable" };
        }
        if (!resultResp.ok) return { status: "unavailable" };
        bundle = await resultResp.json();
      }
      if (!bundle || !Array.isArray(bundle.frames_chronological)) return { status: "unavailable" };
      return bundle.frames_chronological.length
        ? { status: "ready", bundle, cached: job.cached === true }
        : { status: "no-observations" };
    }

    if (job.status === "failed") {
      return { status: job.error_code === "no_observations" ? "no-observations" : "unavailable" };
    }
    return { status: "unavailable" };
  }

  async function readBenchmark(targetId, signal, onProgress) {
    const id = BENCHMARK_ID[targetId] || targetId;
    const config = await readConfig(signal);
    if (!config.liveQueries) throw liveDisabledError();
    return runAsyncJob(
      config.baseHref,
      { query: id, size_arcsec: 180, max_frames: 12 },
      async () => {
        const url = new URL(`api/v1/blink/${encodeURIComponent(id)}`, config.baseHref);
        return parseBundleResponse(await fetchData(url, signal, 120000));
      },
      signal,
      onProgress,
    );
  }

  async function readCustomPosition(ra, dec, signal, onProgress) {
    if (!Number.isFinite(ra) || !Number.isFinite(dec)) {
      return { status: "unavailable" };
    }
    const config = await readConfig(signal);
    if (!config.liveQueries) throw liveDisabledError();
    return runAsyncJob(
      config.baseHref,
      { ra, dec, size_arcsec: 180, max_frames: 12 },
      async () => {
        const url = new URL("api/v1/blink", config.baseHref);
        url.search = new URLSearchParams({ ra, dec, size_arcsec: 180 });
        return parseBundleResponse(await fetchData(url, signal, 120000));
      },
      signal,
      onProgress,
    );
  }

  window.viewerData = {
    async load({ targetId, ra, dec }, signal, onProgress) {
      try {
        return targetId
          ? await readBenchmark(targetId, signal, onProgress)
          : await readCustomPosition(ra, dec, signal, onProgress);
      } catch (error) {
        if (signal.aborted) throw error;
        if (error?.code === "live_disabled") return { status: "live-disabled" };
        return { status: "unavailable" };
      }
    },
  };
})();
