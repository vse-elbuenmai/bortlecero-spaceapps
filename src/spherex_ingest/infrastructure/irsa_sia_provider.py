"""IRSA SIAv2 & On-The-Fly Cutout provider for SPHEREx Level 2b FITS exposures.

Queries NASA/IPAC Infrared Science Archive (IRSA) Simple Image Access v2 (`pyvo.dal.SIA2Service`)
in `spherex_dr1`, `spherex_qr3`, `spherex_dr1_deep`, and `spherex_qr3_deep` collections
(explicitly blocking deprecated `spherex_qr2` per AGENTS.md), downloads server-side spatial
cutouts, caches FITS files locally, and parses them via `SPHERExMEFParser`.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Any

import httpx
import pyvo
from astropy.io import fits
from astropy.io.votable import parse as parse_votable
from astropy.table import Table

from spherex_ingest._atomic_files import atomic_write_bytes
from spherex_ingest.domain.models import (
    CutoutFetchResult,
    DroppedFrameDTO,
    RawCutoutFrame,
    TargetSpec,
)
from spherex_ingest.infrastructure.bounded_http import fetch_bytes, retry_limit, retry_sleep
from spherex_ingest.infrastructure.mef_parser import SPHERExMEFParser
from spherex_ingest.limits import WorkLimitExceeded, active_budget

logger = logging.getLogger(__name__)

DEFAULT_IRSA_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
FITS_BLOCK_BYTES = 2880


class IRSASiaCutoutProvider:
    """Fetches SPHEREx Level 2b cutouts from IRSA SIAv2 with local disk caching and retry."""

    def __init__(
        self,
        sia_url: str = DEFAULT_IRSA_SIA_URL,
        cache_dir: Path = Path(".cache/fits"),
        parser: SPHERExMEFParser | None = None,
        timeout_sec: float = 45.0,
        max_retries: int = 3,
    ) -> None:
        self.sia_url = sia_url
        self.cache_dir = Path(cache_dir)
        self.parser = parser or SPHERExMEFParser()
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    @staticmethod
    def validate_collections(collections: tuple[str, ...] | list[str]) -> None:
        """Ensure deprecated QR2 collections are never queried (per AGENTS.md)."""
        for coll in collections:
            if "qr2" in coll.lower():
                raise ValueError(
                    f"Collection '{coll}' is forbidden: SPHEREx QR2 is superseded by DR1 "
                    "and must never be queried alongside DR1/QR3."
                )

    def fetch_cutouts(
        self,
        target: TargetSpec,
        max_frames_per_collection: int | None = None,
    ) -> CutoutFetchResult:
        """Retrieve raw cutouts and diagnostics for the requested sky position."""
        self.validate_collections(target.collections)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Propagate catalog coordinates to mid-SPHEREx survey (MJD 61000 ~ Nov 2025)
        # so high-proper-motion stars (e.g., Barnard's Star) are centered in the cutout.
        from spherex_ingest.processors.kinematics import KinematicsAndPhotometryAnalyzer

        query_ra_deg, query_dec_deg = KinematicsAndPhotometryAnalyzer().propagate_position(
            target, mjd=61000.0
        )

        priority_bands = getattr(target, "priority_bands", ())
        if not priority_bands and (
            "wise_0855" in target.target_id.lower() or "0855" in target.name
        ):
            priority_bands = (5, 6)

        sia_service = pyvo.dal.SIA2Service(self.sia_url, check_baseurl=False)
        seen_filenames: set[str] = set()
        frames: list[RawCutoutFrame] = []
        dropped_frames: list[DroppedFrameDTO] = []

        budget = active_budget.get()
        with httpx.Client(
            timeout=self.timeout_sec, follow_redirects=True, max_redirects=3 if budget else 20
        ) as client:
            for index, collection in enumerate(target.collections):
                collection_limit = max_frames_per_collection
                if budget:
                    budget.remaining_time()
                    if not budget.exposures_left:
                        break
                    remaining_collections = len(target.collections) - index
                    share = (
                        budget.exposures_left + remaining_collections - 1
                    ) // remaining_collections
                    collection_limit = min(collection_limit, share) if collection_limit else share
                logger.info(
                    "Querying IRSA SIAv2 collection='%s' at RA=%.6f, Dec=%.6f",
                    collection,
                    query_ra_deg,
                    query_dec_deg,
                )
                try:
                    candidates = self._query_collection(
                        sia_service=sia_service,
                        collection=collection,
                        ra_deg=query_ra_deg,
                        dec_deg=query_dec_deg,
                        seen_filenames=seen_filenames,
                        max_frames=collection_limit,
                        priority_bands=priority_bands,
                    )
                except WorkLimitExceeded:
                    raise
                except Exception as exc:
                    logger.warning(
                        "SIAv2 query failed for collection '%s' after retries: %s",
                        collection,
                        exc,
                    )
                    dropped_frames.append(
                        DroppedFrameDTO(
                            frame_id=f"{collection}_query",
                            reason="collection_query_error",
                            error_detail=str(exc),
                        )
                    )
                    continue

                for cand in candidates:
                    if budget:
                        budget.consume_exposure()
                    cutout_url = self.build_cutout_url(
                        base_access_url=cand["access_url"],
                        ra_deg=query_ra_deg,
                        dec_deg=query_dec_deg,
                        size_arcsec=target.cutout_size_arcsec,
                    )
                    try:
                        frame = self._download_and_parse(
                            client=client,
                            cutout_url=cutout_url,
                            base_filename=cand["filename"],
                            collection=collection,
                            target_ra_deg=query_ra_deg,
                            target_dec_deg=query_dec_deg,
                        )
                        frames.append(frame)
                    except WorkLimitExceeded:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "Skipping failed cutout '%s' from %s: %s",
                            cand["filename"],
                            collection,
                            exc,
                        )
                        dropped_frames.append(
                            DroppedFrameDTO(
                                frame_id=cand.get("filename", "unknown"),
                                reason="cutout_download_error",
                                attempted_band=cand.get("band"),
                                obs_date=str(cand.get("t_min")) if cand.get("t_min") else None,
                                error_detail=str(exc),
                            )
                        )

        frames.sort(key=lambda f: (f.mjd_avg, f.detector_band))
        return CutoutFetchResult(frames=tuple(frames), dropped_frames=tuple(dropped_frames))

    @staticmethod
    def _parse_sia_table(data: bytes) -> Table:
        """Decode a discovery response and check its status and schema."""
        document = parse_votable(io.BytesIO(data), table_number=0)
        if any(
            info.name == "QUERY_STATUS" and info.value == "ERROR" for info in document.iter_info()
        ):
            raise ValueError("IRSA reported a failed SIAv2 query.")
        table = document.get_first_table().to_table(use_names_over_ids=True)
        if "access_url" not in table.colnames:
            raise ValueError("SIAv2 response is missing the access_url column.")
        return table

    @staticmethod
    def _publish_cache_entry(path: Path, data: bytes) -> None:
        """Cache a validated response when local scratch storage is writable."""
        try:
            atomic_write_bytes(path, data)
        except OSError as exc:
            logger.warning("Could not publish IRSA cache entry %s: %s", path, exc)

    def _execute_sia_table_with_retry(
        self,
        sia_service: pyvo.dal.SIA2Service,
        collection: str,
        ra_deg: float,
        dec_deg: float,
    ) -> Table:
        """Execute SIAv2 search with local VOTable caching and exponential backoff retries."""
        cache_file = (
            self.cache_dir
            / f"sia_{collection}_{ra_deg:.4f}_{dec_deg:+.4f}.vot".replace("+", "p").replace(
                "-", "m"
            )
        )
        try:
            return self._parse_sia_table(cache_file.read_bytes())
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning("Ignoring unreadable SIAv2 cache entry %s: %s", cache_file, exc)

        last_exc: Exception | None = None
        attempts = retry_limit(self.max_retries)
        for attempt in range(1, attempts + 1):
            try:
                pos_param = f"CIRCLE {ra_deg:.4f} {dec_deg:.4f} 0.01"
                if active_budget.get():
                    with httpx.Client(follow_redirects=True, max_redirects=3) as client:
                        raw_bytes = fetch_bytes(
                            client,
                            self.sia_url,
                            self.timeout_sec,
                            params={"POS": pos_param, "COLLECTION": collection},
                        )
                else:
                    resp = httpx.get(
                        self.sia_url,
                        params={"POS": pos_param, "COLLECTION": collection},
                        timeout=self.timeout_sec,
                        follow_redirects=True,
                    )
                    resp.raise_for_status()
                    raw_bytes = resp.content
                table = self._parse_sia_table(raw_bytes)
            except WorkLimitExceeded:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < attempts:
                    delay = 1.5 * attempt
                    logger.warning(
                        "SIAv2 attempt %d/%d for '%s' failed (%s); retrying in %.1fs...",
                        attempt,
                        attempts,
                        collection,
                        exc,
                        delay,
                    )
                    retry_sleep(delay)
            else:
                self._publish_cache_entry(cache_file, raw_bytes)
                return table

        assert last_exc is not None
        raise last_exc

    def _query_collection(
        self,
        sia_service: pyvo.dal.SIA2Service,
        collection: str,
        ra_deg: float,
        dec_deg: float,
        seen_filenames: set[str],
        max_frames: int | None,
        priority_bands: tuple[int, ...] = (),
    ) -> list[dict[str, Any]]:
        """Query a single SIAv2 collection, filter science FITS, deduplicate, and select epochs."""
        table = self._execute_sia_table_with_retry(
            sia_service=sia_service,
            collection=collection,
            ra_deg=ra_deg,
            dec_deg=dec_deg,
        )
        if len(table) == 0:
            return []

        col_names = set(table.colnames)
        rows: list[dict[str, Any]] = []

        for row in table:
            if "dataproduct_subtype" in col_names:
                subtype = str(row["dataproduct_subtype"]).strip().lower()
                if subtype and subtype != "science":
                    continue

            access_url = str(row["access_url"]).strip()
            if not access_url or ".fits" not in access_url.lower():
                continue

            base_url = access_url.split("?")[0]
            filename = base_url.rsplit("/", 1)[-1]
            if filename in seen_filenames:
                continue

            t_min = (
                float(row["t_min"])
                if "t_min" in col_names and row["t_min"] is not None
                else 0.0
            )
            band = self._infer_band_from_row_or_filename(row, col_names, filename)

            rows.append(
                {
                    "access_url": access_url,
                    "filename": filename,
                    "t_min": t_min,
                    "band": band,
                }
            )

        rows.sort(key=lambda r: (r["t_min"], r["band"], r["filename"]))

        if max_frames is not None and len(rows) > max_frames:
            rows = self._select_balanced_subset(
                rows, max_frames, priority_bands=priority_bands
            )

        for r in rows:
            seen_filenames.add(r["filename"])

        return rows

    @staticmethod
    def _infer_band_from_row_or_filename(
        row: Any,
        col_names: set[str],
        filename: str,
    ) -> int:
        """Infer SPHEREx detector band (1..6) from SIA row metadata or filename pattern."""
        match = re.search(r"[_-]D([1-6])[_.-]", filename, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        if "energy_bandpassname" in col_names and row["energy_bandpassname"] is not None:
            bp = str(row["energy_bandpassname"])
            digits = re.findall(r"[1-6]", bp)
            if digits:
                return int(digits[-1])
        return 1

    @classmethod
    def _select_balanced_subset(
        cls,
        rows: list[dict[str, Any]],
        max_frames: int,
        priority_bands: tuple[int, ...] = (),
    ) -> list[dict[str, Any]]:
        """Select a temporally spread subset across early and late epochs when capped."""
        if len(rows) <= max_frames:
            return rows

        if priority_bands:
            p_rows = [r for r in rows if r.get("band") in priority_bands]
            other_rows = [r for r in rows if r.get("band") not in priority_bands]
            if len(p_rows) >= max_frames:
                return cls._select_balanced_subset(p_rows, max_frames)
            if p_rows:
                rem = max_frames - len(p_rows)
                other_subset = cls._select_balanced_subset(other_rows, rem)
                combined = p_rows + other_subset
                combined.sort(key=lambda r: (r["t_min"], r["band"], r["filename"]))
                return combined

        indices = [
            int(round(i * (len(rows) - 1) / max(1, max_frames - 1))) for i in range(max_frames)
        ]
        seen_idx: set[int] = set()
        selected: list[dict[str, Any]] = []
        for idx in indices:
            if idx not in seen_idx:
                seen_idx.add(idx)
                selected.append(rows[idx])
        return selected

    @staticmethod
    def build_cutout_url(
        base_access_url: str,
        ra_deg: float,
        dec_deg: float,
        size_arcsec: float,
    ) -> str:
        """Append IRSA cutout query parameters to an access_url."""
        separator = "&" if "?" in base_access_url else "?"
        return (
            f"{base_access_url}{separator}"
            f"center={ra_deg:.6f},{dec_deg:.6f}d&size={size_arcsec:.1f}arcsec"
        )

    def _download_and_parse(
        self,
        client: httpx.Client,
        cutout_url: str,
        base_filename: str,
        collection: str,
        target_ra_deg: float,
        target_dec_deg: float,
    ) -> RawCutoutFrame:
        """Download cutout FITS (or load from local cache) and parse into RawCutoutFrame."""
        url_hash = hashlib.sha256(cutout_url.encode("utf-8")).hexdigest()[:12]
        stem = base_filename.replace(".fits", "")
        cache_path = self.cache_dir / f"{stem}_{url_hash}.fits"

        def parse_cutout(data: bytes) -> RawCutoutFrame:
            if not data or len(data) % FITS_BLOCK_BYTES:
                raise ValueError("IRSA FITS response has an incomplete block.")
            with fits.open(io.BytesIO(data), memmap=False, lazy_load_hdus=False) as hdul:
                last_hdu = hdul.fileinfo(len(hdul) - 1)
                if last_hdu is None or last_hdu["datLoc"] + last_hdu["datSpan"] != len(data):
                    raise ValueError("IRSA FITS response has an incomplete or invalid block.")
                return self.parser.parse_hdulist(
                    hdul=hdul,
                    target_ra_deg=target_ra_deg,
                    target_dec_deg=target_dec_deg,
                    collection=collection,
                    source_url=cutout_url,
                    frame_id=stem,
                )

        try:
            return parse_cutout(cache_path.read_bytes())
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning("Ignoring unreadable FITS cache entry %s: %s", cache_path, exc)

        last_exc: Exception | None = None
        attempts = retry_limit(self.max_retries)
        for attempt in range(1, attempts + 1):
            try:
                if active_budget.get():
                    data = fetch_bytes(client, cutout_url, self.timeout_sec)
                else:
                    response = client.get(cutout_url)
                    response.raise_for_status()
                    data = response.content
                frame = parse_cutout(data)
            except WorkLimitExceeded:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < attempts:
                    retry_sleep(1.0 * attempt)
            else:
                self._publish_cache_entry(cache_path, data)
                return frame

        assert last_exc is not None
        raise last_exc
