"""Generate and publish the five default viewer bundles to a private bucket."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from spherex_ingest.domain.targets import BENCHMARK_TARGETS
from spherex_ingest.infrastructure.result_objects import CloudResultObjects
from spherex_ingest.limits import PublicLimits, bounded_ingestion
from spherex_ingest.result_storage import (
    BENCHMARK_MAX_FRAMES,
    BENCHMARK_SIZE_ARCSEC,
    ResultKey,
    benchmark_object_path,
    read_benchmark_bundle,
    validate_benchmark_bundle,
)
from spherex_ingest.service import SPHERExBlinkIngestionService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bucket", help="Private Cloud Storage bucket name")
    parser.add_argument("--fits-cache", type=Path, help="Optional local FITS cache for seeding")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    objects = CloudResultObjects.from_bucket_name(args.bucket)
    service = SPHERExBlinkIngestionService.create_default(cache_dir=args.fits_cache)
    # Match the public viewer's exposure and grid limits, with more time for this offline run.
    limits = PublicLimits(max_elapsed_seconds=300)
    for target_id in BENCHMARK_TARGETS:
        target = service.resolve_target(target_id, cutout_size_arcsec=BENCHMARK_SIZE_ARCSEC)
        key = ResultKey.from_target(target, BENCHMARK_MAX_FRAMES)
        path = benchmark_object_path(key)
        assert path is not None
        if read_benchmark_bundle(objects, key) is not None:
            print(f"{target_id}: already cached", flush=True)
            continue

        with bounded_ingestion(limits, BENCHMARK_MAX_FRAMES):
            bundle = service.ingest_target(
                target, BENCHMARK_SIZE_ARCSEC, BENCHMARK_MAX_FRAMES
            )
        validate_benchmark_bundle(key, bundle)
        objects.write_if_generation(path, bundle.model_dump_json().encode(), expected_generation=0)
        saved = read_benchmark_bundle(objects, key)
        if saved is None:
            raise RuntimeError(f"{target_id}: publication could not be verified")
        print(f"{target_id}: cached {saved.total_frames} frames", flush=True)


if __name__ == "__main__":
    main()
