// Resolve public benchmarks from the static release and live positions via the async jobs API (with local sync fallback).
(() => {
  "use strict";

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

  async function readBundle(url, targetId, signal) {
    const response = await fetchData(url, signal);
    if (!response.ok) return null;
    const raw = await response.json();
    if (raw.target?.target_id !== targetId || !Array.isArray(raw.frames_chronological)) return null;
    return raw;
  }

  async function readBenchmark(targetId, signal) {
    const response = await fetchData("benchmark-manifest.json", signal);
    if (local && response.status === 404) {
      try {
        const bundle = await readBundle(`data/${targetId}/bundle.json`, targetId, signal);
        if (bundle?.frames_chronological.length) return { status: "ready", bundle };
      } catch (error) {
        if (signal.aborted) throw error;
      }
      if (targetId === "barnards_star") {
        const legacy = await fetchData("data/barnard/frames.json", signal);
        if (legacy.ok) {
          const bundle = await legacy.json();
          if (Array.isArray(bundle.frames) && bundle.frames.length) return { status: "ready", bundle };
        }
      }
      return { status: "unavailable" };
    }

    if (!response.ok) return { status: "unavailable" };
    const { version, bundles } = await response.json();
    const expectedPath = `releases/${version}/${targetId}.json`;
    if (!/^[a-f0-9]{64}$/.test(version) || bundles?.[targetId] !== expectedPath) {
      return { status: "unavailable" };
    }
    const bundle = await readBundle(expectedPath, targetId, signal);
    if (!bundle) return { status: "unavailable" };
    return bundle.frames_chronological.length ? { status: "ready", bundle } : { status: "no-observations" };
  }

  async function readCustomPositionLegacy(baseHref, ra, dec, signal) {
    const url = new URL("api/v1/blink", baseHref);
    url.search = new URLSearchParams({ ra, dec, size_arcsec: 180 });
    const result = await fetchData(url, signal, 120000);
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

  async function readCustomPosition(ra, dec, signal) {
    if (!Number.isFinite(ra) || !Number.isFinite(dec)) {
      return { status: "benchmark-only" };
    }
    const response = await fetchData("viewer-config.json", signal);
    if (!response.ok) return { status: "benchmark-only" };
    const { liveQueries, apiBaseUrl } = await response.json();
    if (liveQueries !== true) return { status: "benchmark-only" };

    const base = new URL(apiBaseUrl || location.origin, location.origin);
    const allowedProtocol = base.protocol === "https:"
      || (base.protocol === "http:" && loopback.has(base.hostname));
    if (!allowedProtocol) return { status: "unavailable" };
    const baseHref = base.href.replace(/\/?$/, "/");

    const jobResp = await fetchData(
      new URL("api/v1/jobs", baseHref),
      signal,
      30000,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ra, dec, size_arcsec: 180, max_frames: 12 }),
      },
    );
    if (jobResp.status === 404 || jobResp.status === 405) {
      return readCustomPositionLegacy(baseHref, ra, dec, signal);
    }
    if (jobResp.status === 422) {
      const { detail } = await jobResp.json().catch(() => ({}));
      return { status: detail?.code === "no_observations" ? "no-observations" : "unavailable" };
    }
    if (!jobResp.ok) return { status: "unavailable" };

    let job = await jobResp.json();
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
    }

    if (job.status === "succeeded") {
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
      return bundle.frames_chronological.length ? { status: "ready", bundle } : { status: "no-observations" };
    }

    if (job.status === "failed") {
      return { status: job.error_code === "no_observations" ? "no-observations" : "unavailable" };
    }
    return { status: "unavailable" };
  }

  window.viewerData = {
    async load({ targetId, ra, dec }, signal) {
      try {
        return targetId ? await readBenchmark(targetId, signal) : await readCustomPosition(ra, dec, signal);
      } catch (error) {
        if (signal.aborted) throw error;
        return { status: "unavailable" };
      }
    },
  };
})();
