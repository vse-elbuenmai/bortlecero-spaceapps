"""SPHEREx Level 2b Multi-Extension FITS (MEF) cutout parser.

Handles extraction of science extensions (IMAGE, FLAGS, VARIANCE, ZODI),
SIP distortion header normalization, and 2D spectral WCS (`WCS-WAVE`) evaluation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from spherex_ingest.domain.models import RawCutoutFrame

logger = logging.getLogger(__name__)

# Nominal band centers and spectral resolution bandwidths (um) per SPHEREx band (1..6)
NOMINAL_BAND_WAVELENGTH_UM: dict[int, tuple[float, float]] = {
    1: (0.93, 0.023),
    2: (1.37, 0.033),
    3: (2.03, 0.050),
    4: (3.12, 0.089),
    5: (4.12, 0.037),
    6: (4.71, 0.036),
}


class SPHERExMEFParser:
    """Parser for SPHEREx Level 2b Multi-Extension FITS files and IRSA cutouts."""

    def parse_file(
        self,
        fits_path: Path,
        target_ra_deg: float,
        target_dec_deg: float,
        collection: str = "spherex_dr1",
        source_url: str = "",
        frame_id: str | None = None,
    ) -> RawCutoutFrame:
        """Open a FITS file on disk and parse it into a RawCutoutFrame."""
        resolved_id = frame_id or fits_path.stem
        with fits.open(fits_path, memmap=False) as hdul:
            return self.parse_hdulist(
                hdul=hdul,
                target_ra_deg=target_ra_deg,
                target_dec_deg=target_dec_deg,
                collection=collection,
                source_url=source_url,
                frame_id=resolved_id,
            )

    def parse_hdulist(
        self,
        hdul: fits.HDUList,
        target_ra_deg: float,
        target_dec_deg: float,
        collection: str = "spherex_dr1",
        source_url: str = "",
        frame_id: str | None = None,
    ) -> RawCutoutFrame:
        """Parse an open astropy HDUList into a RawCutoutFrame domain object."""
        img_hdu = hdul["IMAGE"] if "IMAGE" in hdul else hdul[1]
        img_hdr = img_hdu.header
        primary_hdr = hdul[0].header

        image_mjy_sr = np.asarray(img_hdu.data, dtype=np.float32)
        ny, nx = image_mjy_sr.shape

        if "FLAGS" in hdul and hdul["FLAGS"].data is not None:
            flags_bitmask = np.asarray(hdul["FLAGS"].data, dtype=np.uint32)
        else:
            flags_bitmask = np.zeros((ny, nx), dtype=np.uint32)

        if "VARIANCE" in hdul and hdul["VARIANCE"].data is not None:
            variance_mjy2_sr2 = np.asarray(hdul["VARIANCE"].data, dtype=np.float32)
        else:
            variance_mjy2_sr2 = np.zeros((ny, nx), dtype=np.float32)

        if "ZODI" in hdul and hdul["ZODI"].data is not None:
            zodi_mjy_sr = np.asarray(hdul["ZODI"].data, dtype=np.float32)
        else:
            zodi_mjy_sr = np.zeros((ny, nx), dtype=np.float32)

        spatial_wcs = self._build_spatial_wcs(img_hdr)

        detector_band = int(
            self._get_header_val(img_hdr, primary_hdr, ("DETECTOR", "DET_ID", "BAND"), 1)
        )
        mjd_avg = float(
            self._get_header_val(img_hdr, primary_hdr, ("MJD-AVG", "MJD-OBS", "MJD_AVG"), 60800.0)
        )
        obs_time_iso = str(
            self._get_header_val(
                img_hdr, primary_hdr, ("DATE-AVG", "DATE-OBS", "OBS-DATE"), "2025-05-05T00:00:00"
            )
        )
        sps_epa_deg = float(
            self._get_header_val(img_hdr, primary_hdr, ("SPS_EPA", "PA_PNT", "CROTA2"), 0.0)
        )
        finast_flag = int(self._get_header_val(img_hdr, primary_hdr, ("FINAST",), 0))

        # Target pixel coordinates in cutout
        try:
            x_target_arr, y_target_arr = spatial_wcs.wcs_world2pix(target_ra_deg, target_dec_deg, 0)
            x_t = float(np.clip(float(x_target_arr), 0.0, max(0.0, float(nx - 1))))
            y_t = float(np.clip(float(y_target_arr), 0.0, max(0.0, float(ny - 1))))
        except Exception:
            x_t = float(nx) / 2.0
            y_t = float(ny) / 2.0

        (
            wavelength_um,
            bandwidth_um,
            wavelength_map_um,
            bandwidth_map_um,
        ) = self._evaluate_spectral_wcs(
            img_hdr=img_hdr,
            hdul=hdul,
            detector_band=detector_band,
            x_t=x_t,
            y_t=y_t,
            ny=ny,
            nx=nx,
        )

        resolved_id = (
            frame_id
            or str(self._get_header_val(img_hdr, primary_hdr, ("EXPID", "OBSID", "EXTNAME"), ""))
            or f"{collection}_det{detector_band}_{mjd_avg:.5f}"
        )

        raw_meta: dict[str, Any] = {
            "DETECTOR": detector_band,
            "MJD-AVG": mjd_avg,
            "DATE-AVG": obs_time_iso,
            "SPS_EPA": sps_epa_deg,
            "FINAST": finast_flag,
            "NAXIS1": nx,
            "NAXIS2": ny,
        }

        return RawCutoutFrame(
            frame_id=resolved_id,
            collection=collection,
            detector_band=detector_band,
            mjd_avg=mjd_avg,
            obs_time_iso=obs_time_iso,
            sps_epa_deg=sps_epa_deg,
            finast_flag=finast_flag,
            image_mjy_sr=image_mjy_sr,
            flags_bitmask=flags_bitmask,
            variance_mjy2_sr2=variance_mjy2_sr2,
            zodi_mjy_sr=zodi_mjy_sr,
            spatial_wcs=spatial_wcs,
            wavelength_um_at_target=wavelength_um,
            bandwidth_um_at_target=bandwidth_um,
            wavelength_map_um=wavelength_map_um,
            bandwidth_map_um=bandwidth_map_um,
            source_url=source_url,
            raw_header_meta=raw_meta,
        )

    @staticmethod
    def _get_header_val(
        img_hdr: fits.Header,
        primary_hdr: fits.Header,
        keys: tuple[str, ...],
        default: Any,
    ) -> Any:
        """Retrieve the first present header value from IMAGE or PRIMARY headers."""
        for key in keys:
            if key in img_hdr and img_hdr[key] is not None:
                return img_hdr[key]
            if key in primary_hdr and primary_hdr[key] is not None:
                return primary_hdr[key]
        return default

    @staticmethod
    def _build_spatial_wcs(img_hdr: fits.Header) -> WCS:
        """Construct spatial WCS, fixing non-standard SIP CTYPE headers if needed."""
        hdr_copy = img_hdr.copy()
        has_sip = "A_ORDER" in hdr_copy or "B_ORDER" in hdr_copy
        if has_sip:
            ctype1 = str(hdr_copy.get("CTYPE1", "RA---TAN"))
            ctype2 = str(hdr_copy.get("CTYPE2", "DEC--TAN"))
            if not ctype1.endswith("-SIP"):
                hdr_copy["CTYPE1"] = f"{ctype1}-SIP"
            if not ctype2.endswith("-SIP"):
                hdr_copy["CTYPE2"] = f"{ctype2}-SIP"
        return WCS(hdr_copy, naxis=2)

    @staticmethod
    def _evaluate_spectral_wcs(
        img_hdr: fits.Header,
        hdul: fits.HDUList,
        detector_band: int,
        x_t: float,
        y_t: float,
        ny: int,
        nx: int,
    ) -> tuple[float, float, np.ndarray, np.ndarray]:
        """Evaluate SPHEREx Linear Variable Filter wavelength and bandwidth across the cutout."""
        nom_lam, nom_bw = NOMINAL_BAND_WAVELENGTH_UM.get(detector_band, (2.0, 0.05))

        try:
            if "WCS-WAVE" in hdul or "CTYPE1W" in img_hdr:
                hdr_wave = img_hdr.copy()
                for k in list(hdr_wave.keys()):
                    if k.startswith(("A_", "B_", "AP_", "BP_")):
                        del hdr_wave[k]
                w_wave = WCS(hdr_wave, hdul, key="W")
                lam_t, bw_t = w_wave.wcs_pix2world(x_t, y_t, 0)
                lam_val = float(np.asarray(lam_t).item())
                bw_val = float(np.asarray(bw_t).item())

                # Convert from meters to microns if values are in SI meters
                scale = 1e6 if 0.0 < lam_val < 1e-3 else 1.0
                lam_val *= scale
                bw_val = abs(bw_val * scale)

                yy, xx = np.mgrid[0:ny, 0:nx]
                lam_grid, bw_grid = w_wave.wcs_pix2world(xx, yy, 0)
                lam_map = np.asarray(lam_grid, dtype=np.float32) * scale
                bw_map = np.abs(np.asarray(bw_grid, dtype=np.float32) * scale)

                if np.isfinite(lam_val) and lam_val > 0.3:
                    if not np.isfinite(bw_val) or bw_val <= 0.0:
                        bw_val = nom_bw
                    return lam_val, bw_val, lam_map, bw_map
        except Exception as exc:
            logger.debug("Fallback to nominal LVF wavelength for band %d: %s", detector_band, exc)

        # Fallback: check explicit header keywords or synthesize smooth LVF gradient across Y
        lam_center = float(img_hdr.get("WAVELEN", nom_lam))
        bw_center = float(img_hdr.get("BANDWID", nom_bw))
        yy, _ = np.mgrid[0:ny, 0:nx]
        rel_y = (yy - (ny / 2.0)) / max(1.0, float(ny))
        lam_map = (lam_center + 0.04 * rel_y).astype(np.float32)
        bw_map = np.full((ny, nx), bw_center, dtype=np.float32)
        iy = int(np.clip(round(y_t), 0, ny - 1))
        ix = int(np.clip(round(x_t), 0, nx - 1))
        return float(lam_map[iy, ix]), float(bw_map[iy, ix]), lam_map, bw_map
