"""Command-line interface for the SPHEREx Multi-Epoch Blink Comparator ingestion pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from spherex_ingest.domain.models import BlinkBundleDTO, TargetSpec
from spherex_ingest.domain.targets import BENCHMARK_TARGETS, get_benchmark_target
from spherex_ingest.service import SPHERExBlinkIngestionService


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="spherex-ingest",
        description=(
            "SOLID data ingestion, WCS reprojection, Zodi subtraction, and Gaia DR3 "
            "validation pipeline for the NASA Space Apps 2026 SPHEREx Blink Comparator."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level (default: INFO)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. list-benchmarks
    subparsers.add_parser(
        "list-benchmarks",
        help="Print the 5 curated NASA Space Apps benchmark targets and their astrometry",
    )

    # 2. ingest
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest a benchmark target or custom coordinates and export a blink bundle",
    )
    ingest_parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Benchmark target ID or name (e.g., 'barnards_star', 'epsilon_indi_b')",
    )
    ingest_parser.add_argument(
        "--all-benchmarks",
        action="store_true",
        help="Ingest all 5 official NASA Space Apps benchmark targets sequentially",
    )
    ingest_parser.add_argument(
        "--ra",
        type=float,
        default=None,
        help="Custom Right Ascension in decimal degrees (ICRS, 0..360)",
    )
    ingest_parser.add_argument(
        "--dec",
        type=float,
        default=None,
        help="Custom Declination in decimal degrees (ICRS, -90..+90)",
    )
    ingest_parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Custom target display name or object query string",
    )
    ingest_parser.add_argument(
        "--size-arcsec",
        type=float,
        default=180.0,
        help="Square cutout side length in arcseconds (default: 180.0)",
    )
    ingest_parser.add_argument(
        "--max-frames",
        type=int,
        default=24,
        help="Maximum frames per SPHEREx SIAv2 collection (default: 24)",
    )
    ingest_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/fits"),
        help="Directory for caching raw SPHEREx FITS cutouts (default: .cache/fits)",
    )
    ingest_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Output directory for exported bundles and PNGs (default: output)",
    )

    # 3. serve
    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the CORS-enabled FastAPI server via uvicorn",
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Bind host address (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind TCP port (default: 8000)",
    )
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    return parser


def _print_benchmarks(targets: Sequence[TargetSpec]) -> None:
    """Format and print the curated benchmark targets to stdout."""
    header = (
        f"{'TARGET ID':<18} {'NAME':<26} {'CATEGORY':<20} "
        f"{'RA (deg)':>10} {'DEC (deg)':>10} {'PM_RA (mas/yr)':>15} {'PM_DEC (mas/yr)':>16}"
    )
    print(header)
    print("-" * len(header))
    for spec in targets:
        print(
            f"{spec.target_id:<18} {spec.name:<26} {spec.category:<20} "
            f"{spec.ra_deg:>10.5f} {spec.dec_deg:>10.5f} "
            f"{spec.pm_ra_cosdec_mas_yr:>15.2f} {spec.pm_dec_mas_yr:>16.2f}"
        )


def _print_bundle_summary(bundle: BlinkBundleDTO, output_dir: Path) -> None:
    """Print an ingestion summary table of epochs, bands, wavelengths, and astrometric shifts."""
    target_dir = output_dir / bundle.target.target_id
    print(f"\n=== SPHEREx Blink Bundle: {bundle.target.name} ({bundle.target.target_id}) ===")
    print(
        f"Propagated Coords (2026): RA={bundle.propagated_current_ra_deg:.6f} deg, "
        f"Dec={bundle.propagated_current_dec_deg:+.6f} deg"
    )
    print(
        f"Common Grid: {bundle.grid.width_px}x{bundle.grid.height_px} px "
        f"@ {bundle.grid.pixel_scale_arcsec:.2f} arcsec/px ({bundle.grid.orientation})"
    )
    print(
        f"Total Frames: {bundle.total_frames} | "
        f"Available Bands: {bundle.available_bands} | "
        f"Difference Maps: {len(bundle.difference_maps)}"
    )
    print(f"Saved bundle to: {target_dir / 'bundle.json'}\n")

    row_fmt = (
        "{:<24} {:<16} {:>4} {:>12} {:>10} {:>14} {:>14} {:>10}"
    )
    print(
        row_fmt.format(
            "FRAME ID",
            "COLLECTION",
            "BAND",
            "MJD-AVG",
            "WAVE(um)",
            "PRED_PX(x,y)",
            "MEAS_PX(x,y)",
            "OFFSET(\")",
        )
    )
    print("-" * 112)
    for frame in bundle.frames_chronological:
        pred_px = f"{frame.predicted_pixel_x:5.1f},{frame.predicted_pixel_y:5.1f}"
        if frame.measured_centroid_x is not None and frame.measured_centroid_y is not None:
            meas_px = f"{frame.measured_centroid_x:5.1f},{frame.measured_centroid_y:5.1f}"
        else:
            meas_px = "     N/A    "
        offset_str = (
            f"{frame.centroid_offset_arcsec:10.2f}"
            if frame.centroid_offset_arcsec is not None
            else "       N/A"
        )
        print(
            row_fmt.format(
                frame.frame_id[:24],
                frame.collection[:16],
                frame.detector_band,
                f"{frame.mjd_avg:12.4f}",
                f"{frame.wavelength_um:10.3f}",
                pred_px,
                meas_px,
                offset_str,
            )
        )

    if bundle.scientific_warnings:
        print("\nScientific Notes & Warnings:")
        for warning in bundle.scientific_warnings:
            print(f"  - {warning}")


def main(
    argv: Sequence[str] | None = None,
    service: SPHERExBlinkIngestionService | None = None,
) -> int:
    """CLI entrypoint for `spherex-ingest`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "list-benchmarks":
        active_service = service or SPHERExBlinkIngestionService.create_default()
        _print_benchmarks(active_service.list_benchmarks())
        return 0

    if args.command == "serve":
        uvicorn.run(
            "spherex_ingest.api:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0

    if args.command == "ingest":
        active_service = service or SPHERExBlinkIngestionService.create_default(
            cache_dir=args.cache_dir
        )
        targets_to_run: list[TargetSpec | str] = []

        if args.all_benchmarks:
            targets_to_run.extend(BENCHMARK_TARGETS.values())
        elif args.target:
            matched = get_benchmark_target(args.target)
            targets_to_run.append(matched if matched is not None else args.target)
        elif args.ra is not None and args.dec is not None:
            slug = (
                (args.name or f"coord_{args.ra:.4f}_{args.dec:+.4f}")
                .strip()
                .lower()
                .replace(" ", "_")
                .replace("+", "p")
                .replace("-", "m")
                .replace(".", "d")
            )
            targets_to_run.append(
                TargetSpec(
                    target_id=slug,
                    name=args.name or f"RA {args.ra:.5f}d, Dec {args.dec:+.5f}d",
                    category="custom",
                    ra_deg=args.ra,
                    dec_deg=args.dec,
                    cutout_size_arcsec=args.size_arcsec,
                )
            )
        elif args.name:
            targets_to_run.append(args.name)
        else:
            parser.error(
                "Specify one of --target <id>, --all-benchmarks, "
                "--ra <deg> --dec <deg>, or --name <query>."
            )

        for target_item in targets_to_run:
            bundle = active_service.ingest_target(
                target_or_query=target_item,
                cutout_size_arcsec=args.size_arcsec,
                max_frames_per_collection=args.max_frames,
                output_dir=args.output_dir,
            )
            _print_bundle_summary(bundle, args.output_dir)

        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
