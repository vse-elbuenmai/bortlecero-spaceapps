"""Astrometric target resolver backed by curated Gaia DR3 benchmarks and Harvard SIMBAD mirror.

Per AGENTS.md, CDS Strasbourg (`cds.unistra.fr`) is unreachable due to a security incident.
All live catalog lookups strictly route through the Harvard CfA SIMBAD TAP mirror
(`https://simbad.harvard.edu/simbad/sim-tap/sync`).
"""

from __future__ import annotations

import logging
import re

import httpx

from spherex_ingest.domain.models import TargetSpec
from spherex_ingest.domain.targets import get_benchmark_target

logger = logging.getLogger(__name__)

HARVARD_SIMBAD_TAP_URL = "https://simbad.harvard.edu/simbad/sim-tap/sync"

_COORD_PAIR_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*(?:,\s*|\s+)\s*([+-]?\d+(?:\.\d+)?)\s*$"
)


class HarvardSimbadCatalogProvider:
    """Resolves object names or ICRS coordinates into a full TargetSpec."""

    def __init__(
        self,
        tap_url: str = HARVARD_SIMBAD_TAP_URL,
        timeout_sec: float = 20.0,
    ) -> None:
        if "unistra.fr" in tap_url.lower():
            raise ValueError(
                "CDS Strasbourg (unistra.fr) is down; use Harvard mirror (simbad.harvard.edu)."
            )
        self.tap_url = tap_url
        self.timeout_sec = timeout_sec

    def resolve_target(
        self,
        name_or_coord: str,
        cutout_size_arcsec: float = 180.0,
    ) -> TargetSpec:
        """Resolve an astronomical object name or coordinate string into a full TargetSpec."""
        query_str = name_or_coord.strip()
        if not query_str:
            raise ValueError("Target name or coordinate string must not be empty.")

        # 1. Check curated benchmark targets (Gaia DR3 / literature astrometry)
        benchmark = get_benchmark_target(query_str)
        if benchmark is not None:
            return benchmark.model_copy(update={"cutout_size_arcsec": cutout_size_arcsec})

        # 2. Check explicit decimal coordinate pair ("RA, Dec" or "RA Dec")
        coord_match = _COORD_PAIR_RE.match(query_str)
        if coord_match:
            ra_deg = float(coord_match.group(1))
            dec_deg = float(coord_match.group(2))
            slug = (
                f"coord_{ra_deg:.4f}_{dec_deg:+.4f}"
                .replace(".", "p")
                .replace("+", "pos")
                .replace("-", "neg")
            )
            return TargetSpec(
                target_id=slug,
                name=f"ICRS ({ra_deg:.5f}, {dec_deg:+.5f})",
                category="custom",
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                ref_epoch_jyear=2000.0,
                cutout_size_arcsec=cutout_size_arcsec,
            )

        # 3. Query Harvard SIMBAD TAP mirror
        return self._query_harvard_simbad(query_str, cutout_size_arcsec)

    def _query_harvard_simbad(
        self,
        object_name: str,
        cutout_size_arcsec: float,
    ) -> TargetSpec:
        """Query the Harvard SIMBAD TAP service for astrometric parameters."""
        sanitized_name = object_name.replace("'", "''")
        adql = (
            "SELECT TOP 1 basic.main_id, basic.ra, basic.dec, "
            "basic.pmra, basic.pmdec, basic.plx_value, basic.rvz_radvel "
            "FROM basic JOIN ident ON basic.oid = ident.oidref "
            f"WHERE ident.id = '{sanitized_name}'"
        )

        params = {
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "json",
            "QUERY": adql,
        }

        with httpx.Client(timeout=self.timeout_sec, follow_redirects=True) as client:
            response = client.get(self.tap_url, params=params)
            response.raise_for_status()
            payload = response.json()

        data_rows = payload.get("data", [])
        if not data_rows:
            raise LookupError(f"Target '{object_name}' not found in Harvard SIMBAD mirror.")

        row = data_rows[0]
        main_id = str(row[0] or object_name).strip()
        ra_deg = float(row[1])
        dec_deg = float(row[2])
        pm_ra = float(row[3]) if row[3] is not None else 0.0
        pm_dec = float(row[4]) if row[4] is not None else 0.0
        plx = max(0.0, float(row[5])) if row[5] is not None else 0.0
        rv = float(row[6]) if row[6] is not None else 0.0

        slug = re.sub(r"[^a-z0-9]+", "_", object_name.lower()).strip("_") or "simbad_target"

        return TargetSpec(
            target_id=slug,
            name=main_id,
            category="custom",
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            ref_epoch_jyear=2000.0,
            pm_ra_cosdec_mas_yr=pm_ra,
            pm_dec_mas_yr=pm_dec,
            parallax_mas=plx,
            radial_velocity_km_s=rv,
            cutout_size_arcsec=cutout_size_arcsec,
            notes="Resolved via Harvard CfA SIMBAD TAP mirror (J2000.0 reference epoch).",
        )
