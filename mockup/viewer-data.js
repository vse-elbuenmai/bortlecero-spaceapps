// Resolve public benchmarks from the static release. The synchronous API is for local development.
(() => {
  "use strict";

  const loopback = new Set(["localhost", "127.0.0.1", "[::1]"]);
  const local = location.protocol === "http:" && loopback.has(location.hostname);
  const fetchData = (url, signal, timeout = 10000) => fetch(url, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(timeout)]),
    redirect: "error",
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

  async function readCustomPosition(ra, dec, signal) {
    if (!local || !Number.isFinite(ra) || !Number.isFinite(dec)) {
      return { status: "benchmark-only" };
    }
    const response = await fetchData("viewer-config.json", signal);
    if (!response.ok) return { status: "benchmark-only" };
    const { liveQueries, apiBaseUrl } = await response.json();
    if (liveQueries !== true) return { status: "benchmark-only" };

    const base = new URL(apiBaseUrl || location.origin);
    if (!loopback.has(base.hostname) || base.protocol !== "http:") return { status: "unavailable" };
    const url = new URL("api/v1/blink", base.href.replace(/\/?$/, "/"));
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
