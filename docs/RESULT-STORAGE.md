# Blink result storage

The synchronous ingestion API keeps curated benchmark bundles in its existing
`SPHEREX_OUTPUT_DIR` path. This directory is for approved releases and the legacy
default request of 180 arcseconds and up to 24 exposures per collection.
Live queries use a separate result store. The two legacy parameters are an operator
contract for installing unversioned fixtures. Publish scientifically validated
benchmarks through the hosting release process.

## Query keys and versions

Each query key hashes the resolved target specification, including source astrometry,
cutout size, ordered IRSA collections, preferred detector bands, and per-collection
frame limit. Coordinates use round-trip binary64 precision and normalize signed zero.
The key also contains the bundle schema, target catalog, and processing algorithm
versions. Change the corresponding version whenever processing or catalog changes
affect cached results.

An immutable result includes its query key, schema and version metadata, code SHA,
timestamps, frame data, inline PNGs, warnings, and citations. The store creates the
complete SHA-256-addressed bundle before switching the manifest to that bundle. A
reader verifies the bundle digest and its processing metadata. Concurrent writers
use generation preconditions, so both receive the published result.

## Settings

| Environment variable | Default | Purpose |
|---|---|---|
| `SPHEREX_RESULTS_BUCKET` | Unset | Name of the private Cloud Storage bucket for live results. |
| `SPHEREX_RESULTS_DIR` | `.cache/results`, or `results` beside `SPHEREX_CACHE_DIR` | Location of the local SQLite database when Cloud Storage is disabled. |
| `SPHEREX_CODE_SHA` | Source SHA-256 in local development | Set to the full Git commit SHA of the deployed image when using Cloud Storage. |
| `SPHEREX_RESULT_TTL_SECONDS` | `86400` | Reuse lifetime for completed results, from one second to seven days. |
| `SPHEREX_SIA_CACHE_TTL_SECONDS` | `3600` | Revalidate IRSA discovery tables after this period. Set to zero to bypass discovery cache reads. |

A partial result with failed upstream retrievals becomes eligible for refresh after
five minutes. Existing jobs can still read it for the normal result lifetime. Empty
bundles have no reusable result entry. A failed publication leaves the prior manifest
readable. Successful retries can switch the manifest to a new complete bundle.

## Retention and access

- Use uniform bucket-level access and public access prevention on the query bucket.
  Grant the query reader `storage.objects.get` on that bucket. The worker also needs
  `storage.objects.create` and `storage.objects.delete` to upload immutable bundles
  and replace manifests with generation preconditions. Use Application Default
  Credentials from the runtime service accounts.
- Apply a Cloud Storage Delete lifecycle rule at eight days or later to
  `queries/v1/`. Review bucket soft-delete and versioning settings when estimating
  retained storage. Publish only the separately approved benchmark assets through
  public hosting.
- The local SQLite data file is capped at 128 MiB and removes entries older than
  eight days on writes. Allow space for the transaction journal. Clear the local
  results directory while the service is stopped when a full cache needs immediate
  cleanup.
- Raw FITS files stay in local scratch storage. Use the bounded Cloud Run scratch
  volume with worker-scoped temporary directories that are removed after each job.
  For local CLI and legacy API development, periodically clear the configured FITS
  cache with the service stopped. Discovery tables in that cache expire independently.
