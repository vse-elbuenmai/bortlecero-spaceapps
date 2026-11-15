"""Stage the explicit public viewer assets and a content-addressed benchmark release."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    "index.html",
    "mockup.css",
    "mockup.js",
    "viewer-data.js",
    "viewer-config.json",
    "sky.css",
    "sky.js",
    "sky/sky.json",
    "sky/visible_2048.webp",
    "sky/visible_4096.webp",
    "sky/spherex-477_2048.webp",
    "sky/spherex-477_4096.webp",
    "sky/spherex-rgb_2048.webp",
    "sky/spherex-rgb_4096.webp",
)
BENCHMARKS = (
    "barnards_star",
    "epsilon_indi_b",
    "wise_0855_0714",
    "rw_aurigae",
    "r_draconis",
)


def build_hosting(source: Path, destination: Path) -> str:
    """Build fresh output so obsolete or unrelated files cannot enter a release."""
    bundles = {
        target: (source / "data" / target / "bundle.json").read_bytes()
        for target in BENCHMARKS
    }
    checksums = {target: hashlib.sha256(bundle).hexdigest() for target, bundle in bundles.items()}
    version = hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest()

    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / "hosting"
        for relative in PUBLIC_FILES:
            path = staged / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, path)

        release = staged / "releases" / version
        release.mkdir(parents=True)
        manifest = {"version": version, "bundles": {}}
        for target, bundle in bundles.items():
            path = release / f"{target}.json"
            path.write_bytes(bundle)
            manifest["bundles"][target] = path.relative_to(staged).as_posix()
        (staged / "benchmark-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        staged.replace(destination)
    return version


if __name__ == "__main__":
    release = build_hosting(ROOT / "mockup", ROOT / "dist" / "hosting")
    print(f"Staged benchmark release {release} in dist/hosting")
