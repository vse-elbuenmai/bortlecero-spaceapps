// Load SPHEREx blink bundles from browser storage or the IRSA ingestion API.
(() => {
  "use strict";

  const BENCHMARK_ID = {
    barnard: "barnards_star",
    epsindib: "epsilon_indi_b",
    wise0855: "wise_0855_0714",
    rwaur: "rw_aurigae",
    rdra: "r_draconis",
  };

  const CACHE_TTL_MS = 60 * 60 * 1000;
  const CACHE_MAX_BYTES = 24 * 1024 * 1024;
  const CACHE_MAX_ENTRIES = 24;
  const upstreamDrops = new Set(["collection_query_error", "cutout_download_error"]);

  // Path-style GCS URLs share a browser origin with unrelated public buckets.
  const sharedGcsOrigin = location.hostname === "storage.googleapis.com";
  let cacheConnection;
  function openBundleCache() {
    if (sharedGcsOrigin) return null;
    cacheConnection ??= new Promise((resolve, reject) => {
      const request = indexedDB.open("bortle-cero-blink", 1);
      let blocked = false;
      request.onupgradeneeded = () => {
        request.result.createObjectStore("bundles").createIndex("savedAt", "savedAt");
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => {
        blocked = true;
        reject(new Error("Blink cache is blocked"));
      };
      request.onsuccess = () => {
        const db = request.result;
        if (blocked) {
          db.close();
          return;
        }
        db.onversionchange = db.onclose = () => {
          db.close();
          cacheConnection = undefined;
        };
        resolve(db);
      };
    }).catch(() => null);
    return cacheConnection;
  }

  async function readCachedBundle(key) {
    const db = await openBundleCache();
    if (!db) return null;
    const entry = await new Promise((resolve, reject) => {
      const request = db.transaction("bundles").objectStore("bundles").get(key);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    if (!entry || Date.now() - entry.savedAt >= CACHE_TTL_MS) return null;
    const bundle = JSON.parse(await entry.body.text());
    return Array.isArray(bundle?.frames_chronological) && bundle.frames_chronological.length
      ? bundle : null;
  }

  async function saveCachedBundle(key, bundle) {
    if (sharedGcsOrigin) return;
    // Retry results missing upstream data on the server's shorter refresh schedule.
    if (bundle.dropped_frames?.some((frame) => upstreamDrops.has(frame.reason))) return;
    const body = new Blob([JSON.stringify(bundle)]);
    if (body.size > CACHE_MAX_BYTES) return;
    const db = await openBundleCache();
    if (!db) return;

    const savedAt = Date.now();
    const transaction = db.transaction("bundles", "readwrite");
    const store = transaction.objectStore("bundles");
    return new Promise((resolve, reject) => {
      transaction.oncomplete = resolve;
      transaction.onabort = () => reject(transaction.error);
      let bytes = body.size;
      let count = 1;
      // Keep pruning and the write atomic, including when several tabs share the cache.
      const entries = store.index("savedAt").openCursor(null, "prev");
      entries.onsuccess = () => {
        const cursor = entries.result;
        if (!cursor) {
          store.put({ savedAt, body }, key);
          return;
        }
        const { savedAt: previous, body: stored } = cursor.value;
        if (cursor.primaryKey === key || savedAt - previous >= CACHE_TTL_MS
            || count >= CACHE_MAX_ENTRIES || bytes + stored.size > CACHE_MAX_BYTES) {
          cursor.delete();
        } else {
          count += 1;
          bytes += stored.size;
        }
        cursor.continue();
      };
    });
  }

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

  async function loadBundle(payload, fallbackFn, signal, onProgress) {
    const config = await readConfig(signal);
    if (!config.liveQueries) throw liveDisabledError();
    // Bump the key version when old bundles are incompatible with the viewer.
    const key = JSON.stringify([1, config.baseHref, payload]);
    const cached = await readCachedBundle(key).catch(() => null);
    signal.throwIfAborted();
    if (cached) return { status: "ready", bundle: cached, cached: true };
    const result = await runAsyncJob(
      config.baseHref, payload, () => fallbackFn(config.baseHref), signal, onProgress,
    );
    if (!signal.aborted && result.status === "ready") {
      saveCachedBundle(key, result.bundle).catch(() => {});
    }
    return result;
  }

  async function readBenchmark(targetId, signal, onProgress) {
    const id = BENCHMARK_ID[targetId] || targetId;
    return loadBundle(
      { query: id, size_arcsec: 180, max_frames: 12 },
      async (baseHref) => {
        const url = new URL(`api/v1/blink/${encodeURIComponent(id)}`, baseHref);
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
    return loadBundle(
      { ra, dec, size_arcsec: 180, max_frames: 12 },
      async (baseHref) => {
        const url = new URL("api/v1/blink", baseHref);
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
