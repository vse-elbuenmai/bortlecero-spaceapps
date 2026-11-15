"""Frontend bundle exporter producing JSON payloads, arcsinh PNG frames, and difference maps."""

from __future__ import annotations

import base64
import io
import itertools
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from astropy.wcs import WCS
from PIL import Image

from spherex_ingest._atomic_files import atomic_write_bytes
from spherex_ingest.domain.models import (
    BlinkBundleDTO,
    CommonGridSpecDTO,
    DifferenceMapDTO,
    DroppedFrameDTO,
    FrameMetadataDTO,
    ProcessedBlinkFrame,
    TargetSpec,
)
from spherex_ingest.limits import active_budget

DEFAULT_CITATIONS: tuple[str, ...] = (
    "SPHEREx Explanatory Supplement & Data Release 1 / Quick Release 3 (NASA/IPAC IRSA, 2026)",
    "Akeson, R., et al. (2026), ApJS, 285, 67 — The SPHEREx Science Archive at IRSA",
    "Gaia Collaboration, Vallenari, A., et al. (2023), A&A, 674, A1 — Gaia Data Release 3",
    "Astropy Collaboration (2022), ApJ, 935, 167 — The Astropy Project",
)


class FrontendBundleExporter:
    """Serializes processed SPHEREx blink frames into a frontend-ready BlinkBundleDTO."""

    def __init__(self, min_diff_baseline_days: float = 1.0, upscale_factor: int = 4) -> None:
        self._min_diff_baseline_days = min_diff_baseline_days
        self._upscale_factor = max(1, upscale_factor)

    def build_bundle(
        self,
        target: TargetSpec,
        processed_frames: Sequence[ProcessedBlinkFrame],
        common_wcs: WCS,
        grid_shape: tuple[int, int],
        dropped_frames: Sequence[DroppedFrameDTO] = (),
    ) -> BlinkBundleDTO:
        """Assemble the complete BlinkBundleDTO including difference maps and warnings."""
        sorted_frames = sorted(
            processed_frames, key=lambda f: (f.mjd_avg, f.detector_band, f.frame_id)
        )
        all_dropped: list[DroppedFrameDTO] = list(dropped_frames)

        # Filter out frames with low valid pixel fraction (< 0.40)
        retained_frames: list[ProcessedBlinkFrame] = []
        for frame in sorted_frames:
            total_px = max(1, frame.reprojected_image_mjy_sr.size)
            valid_px = int(
                np.count_nonzero(
                    np.isfinite(frame.reprojected_image_mjy_sr)
                    & (~frame.bad_pixel_mask)
                    & frame.footprint_mask
                )
            )
            valid_frac = round(float(valid_px) / float(total_px), 4)
            if valid_frac < 0.40:
                all_dropped.append(
                    DroppedFrameDTO(
                        frame_id=frame.frame_id,
                        reason="low_valid_pixel_fraction",
                        attempted_band=frame.detector_band,
                        obs_date=frame.obs_time_iso,
                        error_detail=f"valid_pixel_fraction={valid_frac:.4f} < 0.40 threshold",
                    )
                )
            else:
                retained_frames.append(frame)

        band_scales = self._compute_band_display_scales(retained_frames)

        frames_chronological: list[FrameMetadataDTO] = []
        frames_by_band_dict: dict[str, list[FrameMetadataDTO]] = defaultdict(list)

        budget = active_budget.get()
        for frame in retained_frames:
            if budget:
                budget.remaining_time()
            vmin, vmax, softening = band_scales.get(frame.detector_band, (0.0, 10.0, 1.0))
            display_arr = (
                frame.repaired_image_mjy_sr
                if frame.repaired_image_mjy_sr is not None
                else frame.reprojected_image_mjy_sr
            )
            png_b64 = (
                frame.png_base64
                if frame.png_base64 is not None
                else self._render_arcsinh_png_base64(
                    display_arr,
                    vmin=vmin,
                    vmax=vmax,
                    softening=softening,
                    saturation_mask=frame.saturation_mask,
                )
            )
            dto = self._to_frame_dto(frame, png_b64=png_b64)
            frames_chronological.append(dto)
            frames_by_band_dict[str(frame.detector_band)].append(dto)

        difference_maps = self._build_difference_maps(retained_frames)
        warnings = self._generate_scientific_warnings(
            target,
            retained_frames,
            difference_maps=difference_maps,
            dropped_frames=all_dropped,
        )
        available_bands = sorted({f.detector_band for f in retained_frames})

        ny, nx = grid_shape
        pixel_scale_arcsec = float(abs(common_wcs.wcs.cdelt[1]) * 3600.0)
        center_ra = float(common_wcs.wcs.crval[0])
        center_dec = float(common_wcs.wcs.crval[1])

        grid_dto = CommonGridSpecDTO(
            center_ra_deg=center_ra,
            center_dec_deg=center_dec,
            pixel_scale_arcsec=round(pixel_scale_arcsec, 4),
            width_px=int(nx),
            height_px=int(ny),
        )

        return BlinkBundleDTO(
            target=target,
            propagated_current_ra_deg=center_ra,
            propagated_current_dec_deg=center_dec,
            grid=grid_dto,
            total_frames=len(frames_chronological),
            available_bands=available_bands,
            frames_chronological=frames_chronological,
            frames_by_band=dict(frames_by_band_dict),
            difference_maps=difference_maps,
            dropped_frames=all_dropped,
            scientific_warnings=warnings,
            citations=list(DEFAULT_CITATIONS),
        )

    def save_bundle(
        self,
        bundle: BlinkBundleDTO,
        output_dir: Path,
    ) -> Path:
        """Publish the self-contained JSON bundle and standalone PNG exports."""
        target_dir = Path(output_dir) / bundle.target.target_id
        frames_dir = target_dir / "frames"
        diffs_dir = target_dir / "differences"
        frames_dir.mkdir(parents=True, exist_ok=True)
        diffs_dir.mkdir(parents=True, exist_ok=True)

        for frame in bundle.frames_chronological:
            if frame.png_base64 and "," in frame.png_base64:
                raw_bytes = base64.b64decode(frame.png_base64.split(",", 1)[1])
                safe_id = "".join(
                    c if (c.isalnum() or c in ("-", "_")) else "_" for c in frame.frame_id
                )
                atomic_write_bytes(frames_dir / f"{safe_id}.png", raw_bytes)

        for diff in bundle.difference_maps:
            if diff.png_base64 and "," in diff.png_base64:
                raw_bytes = base64.b64decode(diff.png_base64.split(",", 1)[1])
                fname = (
                    f"diff_band{diff.detector_band}_"
                    f"{diff.frame_id_early}_vs_{diff.frame_id_late}.png"
                )
                safe_fname = "".join(
                    c if (c.isalnum() or c in ("-", "_", ".")) else "_" for c in fname
                )
                atomic_write_bytes(diffs_dir / safe_fname, raw_bytes)

        # The JSON includes its own images, so readers obtain one complete snapshot.
        bundle_path = target_dir / "bundle.json"
        atomic_write_bytes(bundle_path, bundle.model_dump_json(indent=2).encode("utf-8"))
        return bundle_path

    def _compute_band_display_scales(
        self,
        frames: Sequence[ProcessedBlinkFrame],
    ) -> dict[int, tuple[float, float, float]]:
        """Compute consistent (vmin, vmax, softening) per band to preserve brightness changes."""
        by_band: dict[int, list[np.ndarray]] = defaultdict(list)
        for frame in frames:
            arr = (
                frame.repaired_image_mjy_sr
                if frame.repaired_image_mjy_sr is not None
                else frame.reprojected_image_mjy_sr
            )
            finite = arr[np.isfinite(arr)]
            if finite.size > 0:
                by_band[frame.detector_band].append(finite)

        scales: dict[int, tuple[float, float, float]] = {}
        for band, arrays in by_band.items():
            pooled = np.concatenate(arrays)
            vmin = float(np.percentile(pooled, 10.0))
            vmax = float(np.percentile(pooled, 99.5))
            if vmax <= vmin + 1e-6:
                vmax = vmin + 1.0
            med = float(np.median(pooled))
            mad = float(np.median(np.abs(pooled - med)))
            softening = max(1.4826 * mad * 3.0, (vmax - vmin) * 0.08, 1e-3)
            scales[band] = (vmin, vmax, softening)
        return scales

    def _render_arcsinh_png_base64(
        self,
        image_mjy_sr: np.ndarray,
        vmin: float,
        vmax: float,
        softening: float,
        saturation_mask: np.ndarray | None = None,
    ) -> str:
        """Render a 2D array into an 8-bit RGB PNG using North-up arcsinh stretch."""
        flipped_img = np.flipud(image_mjy_sr)
        arr = np.nan_to_num(flipped_img, nan=vmin)
        clipped = np.clip(arr - vmin, 0.0, max(vmax - vmin, 1e-6))
        denom = float(np.arcsinh((vmax - vmin) / softening))
        if denom <= 0.0:
            denom = 1.0
        norm = np.clip(np.arcsinh(clipped / softening) / denom, 0.0, 1.0)

        # Warm astronomical colormap (deep space navy -> amber -> white core)
        r = np.clip(np.power(norm, 0.75) * 255.0, 0, 255).astype(np.uint8)
        g = np.clip(np.power(norm, 1.05) * 245.0, 0, 255).astype(np.uint8)
        b = np.clip((0.12 + 0.88 * np.power(norm, 1.45)) * 255.0, 0, 255).astype(np.uint8)

        if saturation_mask is not None and np.any(saturation_mask):
            flipped_sat = np.flipud(saturation_mask)
            # Subtle cyan-white highlight on repaired saturated core pixels
            r = np.where(flipped_sat, np.maximum(r, 235), r)
            g = np.where(flipped_sat, np.maximum(g, 250), g)
            b = np.where(flipped_sat, 255, b)

        rgb = np.stack([r, g, b], axis=-1)
        pil_img = Image.fromarray(rgb, mode="RGB")
        if self._upscale_factor > 1:
            ny, nx = image_mjy_sr.shape
            pil_img = pil_img.resize(
                (nx * self._upscale_factor, ny * self._upscale_factor),
                resample=Image.Resampling.NEAREST,
            )

        buf = io.BytesIO()
        pil_img.save(buf, format="PNG", optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _render_diverging_png_base64(self, diff_mjy_sr: np.ndarray) -> str:
        """Render a North-up bipolar difference image (blue = neg, orange/white = pos)."""
        flipped_diff = np.flipud(diff_mjy_sr)
        finite = flipped_diff[np.isfinite(flipped_diff)]
        if finite.size > 0:
            lim = float(np.percentile(np.abs(finite), 99.0))
        else:
            lim = 1.0
        lim = max(lim, 1e-4)

        norm = np.clip(np.nan_to_num(flipped_diff, nan=0.0) / lim, -1.0, 1.0)
        pos = np.clip(norm, 0.0, 1.0)
        neg = np.clip(-norm, 0.0, 1.0)

        r = np.clip((pos * 255.0 + neg * 30.0), 0, 255).astype(np.uint8)
        g = np.clip((np.power(pos, 1.3) * 190.0 + np.power(neg, 1.1) * 150.0), 0, 255).astype(
            np.uint8
        )
        b = np.clip((np.power(pos, 2.0) * 90.0 + neg * 255.0), 0, 255).astype(np.uint8)

        rgb = np.stack([r, g, b], axis=-1)
        pil_img = Image.fromarray(rgb, mode="RGB")
        if self._upscale_factor > 1:
            ny, nx = diff_mjy_sr.shape
            pil_img = pil_img.resize(
                (nx * self._upscale_factor, ny * self._upscale_factor),
                resample=Image.Resampling.NEAREST,
            )

        buf = io.BytesIO()
        pil_img.save(buf, format="PNG", optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _build_difference_maps(
        self,
        frames: Sequence[ProcessedBlinkFrame],
    ) -> list[DifferenceMapDTO]:
        """Compute I(t_late) - I(t_early) difference maps within each spectral band.

        Selects the frame pair separated by at least min_diff_baseline_days that
        minimizes the wavelength variation |lambda_late - lambda_early| across the
        Linear Variable Filter (LVF).
        """
        by_band: dict[int, list[ProcessedBlinkFrame]] = defaultdict(list)
        for frame in frames:
            by_band[frame.detector_band].append(frame)

        diffs: list[DifferenceMapDTO] = []
        for band in sorted(by_band.keys()):
            band_frames = sorted(by_band[band], key=lambda f: f.mjd_avg)
            if len(band_frames) < 2:
                continue

            candidate_pairs = [
                (f1, f2)
                for f1, f2 in itertools.combinations(band_frames, 2)
                if (f2.mjd_avg - f1.mjd_avg) >= self._min_diff_baseline_days
            ]
            if not candidate_pairs:
                continue

            early, late = min(
                candidate_pairs,
                key=lambda pair: (
                    round(abs(pair[1].wavelength_um - pair[0].wavelength_um), 5),
                    -abs(pair[1].mjd_avg - pair[0].mjd_avg),
                ),
            )

            baseline_days = float(late.mjd_avg - early.mjd_avg)

            arr_early = (
                early.repaired_image_mjy_sr
                if early.repaired_image_mjy_sr is not None
                else early.reprojected_image_mjy_sr
            )
            arr_late = (
                late.repaired_image_mjy_sr
                if late.repaired_image_mjy_sr is not None
                else late.reprojected_image_mjy_sr
            )
            diff_arr = arr_late - arr_early
            png_b64 = self._render_diverging_png_base64(diff_arr)

            early_lam = round(float(early.wavelength_um), 4)
            late_lam = round(float(late.wavelength_um), 4)
            delta_lam = round(float(abs(late.wavelength_um - early.wavelength_um)), 4)
            mean_lam = round(0.5 * (early.wavelength_um + late.wavelength_um), 4)

            diffs.append(
                DifferenceMapDTO(
                    detector_band=band,
                    frame_id_early=early.frame_id,
                    frame_id_late=late.frame_id,
                    mjd_early=early.mjd_avg,
                    mjd_late=late.mjd_avg,
                    baseline_days=round(baseline_days, 4),
                    mean_wavelength_um=mean_lam,
                    early_wavelength_um=early_lam,
                    late_wavelength_um=late_lam,
                    delta_wavelength_um=delta_lam,
                    diff_matrix_mjy_sr=self._matrix_to_nullable_list(diff_arr),
                    png_base64=png_b64,
                )
            )
        return diffs

    def _to_frame_dto(self, frame: ProcessedBlinkFrame, png_b64: str) -> FrameMetadataDTO:
        """Convert a ProcessedBlinkFrame into a JSON-serializable FrameMetadataDTO."""
        sat_count = int(np.count_nonzero(frame.saturation_mask))
        bad_count = int(np.count_nonzero(frame.bad_pixel_mask))
        total_px = max(1, frame.reprojected_image_mjy_sr.size)
        valid_px = int(
            np.count_nonzero(
                np.isfinite(frame.reprojected_image_mjy_sr)
                & (~frame.bad_pixel_mask)
                & frame.footprint_mask
            )
        )
        display_arr = (
            frame.repaired_image_mjy_sr
            if frame.repaired_image_mjy_sr is not None
            else frame.reprojected_image_mjy_sr
        )

        ny = frame.reprojected_image_mjy_sr.shape[0]
        pred_y_display = (ny - 1) - frame.predicted_pixel_y
        meas_y_display = (
            (ny - 1) - frame.measured_centroid_y
            if frame.measured_centroid_y is not None
            else None
        )

        return FrameMetadataDTO(
            frame_id=frame.frame_id,
            collection=frame.collection,
            detector_band=frame.detector_band,
            mjd_avg=frame.mjd_avg,
            obs_time_iso=frame.obs_time_iso,
            sps_epa_deg=frame.sps_epa_deg,
            wavelength_um=frame.wavelength_um,
            bandwidth_um=frame.bandwidth_um,
            predicted_ra_deg=frame.predicted_ra_deg,
            predicted_dec_deg=frame.predicted_dec_deg,
            predicted_pixel_x=frame.predicted_pixel_x,
            predicted_pixel_y=round(pred_y_display, 3),
            measured_centroid_x=frame.measured_centroid_x,
            measured_centroid_y=round(meas_y_display, 3) if meas_y_display is not None else None,
            measured_ra_deg=frame.measured_ra_deg,
            measured_dec_deg=frame.measured_dec_deg,
            centroid_offset_arcsec=frame.centroid_offset_arcsec,
            aperture_flux_ujy=frame.aperture_flux_ujy,
            aperture_flux_err_ujy=frame.aperture_flux_err_ujy,
            snr=frame.snr,
            is_saturated_core=frame.is_saturated_core,
            saturated_pixel_count=sat_count,
            bad_artifact_pixel_count=bad_count,
            valid_pixel_fraction=round(float(valid_px) / float(total_px), 4),
            matrix_mjy_sr=self._matrix_to_nullable_list(display_arr),
            saturation_mask=np.flipud(frame.saturation_mask).astype(bool).tolist(),
            bad_pixel_mask=np.flipud(frame.bad_pixel_mask).astype(bool).tolist(),
            png_base64=png_b64,
            source_url=frame.source_url,
        )

    @staticmethod
    def _matrix_to_nullable_list(arr: np.ndarray) -> list[list[float | None]]:
        """Serialize a 2D numpy array to nested lists (North-up, None for NaN/Inf)."""
        flipped = np.flipud(arr)
        rows: list[list[float | None]] = []
        for row in flipped:
            rows.append([round(float(val), 5) if np.isfinite(val) else None for val in row])
        return rows

    @staticmethod
    def _generate_scientific_warnings(
        target: TargetSpec,
        frames: Sequence[ProcessedBlinkFrame],
        difference_maps: Sequence[DifferenceMapDTO] = (),
        dropped_frames: Sequence[DroppedFrameDTO] = (),
    ) -> list[str]:
        """Generate context-aware scientific warnings for the frontend UI."""
        warnings: list[str] = []
        if not frames:
            warnings.append("No SPHEREx cutouts matched the requested coordinates and collections.")
            if dropped_frames:
                warnings.append(
                    f"{len(dropped_frames)} candidate frame(s) were dropped or excluded during "
                    "processing."
                )
            return warnings

        epa_values = [f.sps_epa_deg for f in frames]
        if max(epa_values) - min(epa_values) > 90.0:
            warnings.append(
                "180-degree spacecraft roll (SPS_EPA) flip detected across survey passes; "
                "all frames have been WCS-reprojected onto a common North-up, East-left TAN grid."
            )

        bands = {f.detector_band for f in frames}
        if len(bands) > 1:
            warnings.append(
                "SPHEREx Linear Variable Filters sample a different wavelength per exposure. "
                "Compare brightness strictly within the same detector band to distinguish true "
                "variability from the star's spectral energy distribution (SED)."
            )

        large_delta_diffs = [d for d in difference_maps if d.delta_wavelength_um > 0.05]
        if large_delta_diffs:
            bands_str = ", ".join(str(d.detector_band) for d in large_delta_diffs)
            warnings.append(
                f"Wavelength difference delta_lambda > 0.05 um detected in difference maps "
                f"for band(s) {bands_str}. Residual flux differences may include spectral energy "
                "distribution (SED) variation across the Linear Variable Filter."
            )

        sat_frames = [f for f in frames if f.is_saturated_core]
        if sat_frames:
            warnings.append(
                f"Detector core saturation (OVERFLOW / NaN core) detected in {len(sat_frames)}/"
                f"{len(frames)} frames. Visual cores are reconstructed from the 98th-percentile "
                "PSF halo; astrometric centroids use halo center-of-mass."
            )

        if dropped_frames:
            reasons = ", ".join(sorted({d.reason for d in dropped_frames}))
            warnings.append(
                f"{len(dropped_frames)} frame(s) were dropped or excluded during processing "
                f"({reasons}: {', '.join(d.frame_id for d in dropped_frames[:3])}"
                f"{'...' if len(dropped_frames) > 3 else ''})."
            )

        if "wise_0855" in target.target_id.lower() or "0855" in target.name:
            warnings.append(
                "WISE 0855-0714 (~250 K Y dwarf) is only detectable at lambda > 3.9 um "
                "(SPHEREx Bands 5 and 6) and lies ~20 pixels West of its 2010 discovery coordinate."
            )

        if target.notes:
            warnings.append(f"Target note: {target.notes}")

        return warnings
