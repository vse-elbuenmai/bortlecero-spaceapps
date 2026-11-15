# Public ingestion limits

Staging starts with live queries disabled. When queued ingestion is enabled, it should be the
sole public path to live work. Keep the synchronous development API disabled in the hosted
service. To stop new live requests, disable the API capability and viewer flag. Pause Cloud
Tasks if existing queued work must stop dispatching too.

| Limit | Default | Environment variable |
| --- | --- | --- |
| Exposures attempted per job across all collections | 12 | `SPHEREX_MAX_EXPOSURES` |
| Output grid pixels | 961 (31 × 31) | `SPHEREX_MAX_GRID_PIXELS` |
| Downloaded bytes per attempt, including discovery and retries | 96 MiB | `SPHEREX_MAX_DOWNLOAD_BYTES` |
| Cooperative processing deadline per attempt | 120 seconds | `SPHEREX_MAX_ELAPSED_SECONDS` |
| Upstream attempts per discovery request or exposure | 2 | `SPHEREX_MAX_UPSTREAM_ATTEMPTS` |
| New unique jobs admitted globally each minute | 6 | `SPHEREX_MAX_NEW_JOBS_PER_MINUTE` |
| Outstanding jobs across service instances | 8 | `SPHEREX_MAX_OUTSTANDING_JOBS` |

These are starting values for staging. The previous cold custom search took 64 seconds and
individual cutouts are about 4 MiB, so a 12-exposure request is expected to transfer about 48 MiB
before discovery, retries, or cache hits. An offline run with 12 cached R Draconis FITS files
processed 45.8 MiB of input into a 521 KiB JSON bundle in 2.75 seconds and reached about 180 MiB
peak process RSS, including Python startup. The profile measures the pipeline with a warm FITS
cache. Use one worker and one simultaneous Cloud Tasks dispatch initially. Worker HTTP and dispatch deadlines must exceed the processing budget and
leave time to record a terminal state. The deadline is checked between operations and during
streaming. Native calls and a single blocking HTTP operation can finish after it.

At a sustained one 120-second attempt at a time, the worker can consume up to 60 vCPU-minutes
and 60 GiB-minutes of memory per wall-clock hour at 1 vCPU and 1 GiB. Each attempt can transfer
up to 96 MiB from IRSA. Cloud Tasks delivery and retries, Firestore admission and status
operations, Cloud Storage reads/writes and retained bytes, and result egress are separate
meters. Measure saved bundle bytes and actual reads per job before raising limits. Configure a
project-scoped budget alert before enabling the public queue. Budget alerts notify operators.
Worker and queue ceilings control concurrent execution.

The queue owns distributed admission and terminal states. Existing equivalent jobs should be
returned before consuming a new admission. A full queue or exhausted admission window returns
HTTP 429 with `Retry-After`. Reject refresh requests at submission. Failed public requests should
return stable codes and correlation IDs while keeping exception details in restricted logs.
