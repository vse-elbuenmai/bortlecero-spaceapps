#!/usr/bin/env python3
"""Verify an already built ingestion image locally, with no upstream network access."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

CONTAINER_PORT = "8189"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests/fixtures/container"
VERIFY_HTTP = """
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

base = f"http://127.0.0.1:{os.environ['PORT']}/api/v1"

def get(path, status=200):
    try:
        with urlopen(base + path, timeout=5) as response:
            assert response.status == status, response.status
            return json.load(response)
    except HTTPError as error:
        assert error.code == status, error.code
        return json.load(error)

deadline = time.monotonic() + 45
while True:
    try:
        health = get("/health")
        break
    except URLError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.25)

assert os.getuid() != 0
assert "uvicorn" in Path("/proc/1/cmdline").read_text()
assert health["status"] == "ok"
assert health["revision"] == "container-smoke"
assert health["legacy_sync_enabled"] is False
assert get("/blink/epsilon_indi_b")["target"]["name"] == "Synthetic container fixture"
for path in (
    "/blink?ra=331&dec=-56",
    "/blink/epsilon_indi_b?force_refresh=true",
    "/blink/barnards_star",
):
    assert get(path, 503)["detail"] == "Live SPHEREx ingestion is disabled."

scratch_file = Path("/scratch/write-test")
scratch_file.write_text("scratch can be written by the runtime user")
scratch_file.unlink()
"""


def docker(*args: str, input_text: str | None = None) -> str:
    """Run Docker and capture its standard output for assertions."""
    result = subprocess.run(
        ["docker", *args],
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stdout.strip())
    return result.stdout.strip()


def smoke(image: str) -> None:
    """Check startup, HTTP behavior, shutdown, and restart of the production entrypoint."""
    container = docker(
        "run",
        "--detach",
        "--network=none",
        "--read-only",
        "--cpus=1",
        "--memory=1g",
        "--tmpfs=/scratch:size=256m,mode=1777",
        f"--env=PORT={CONTAINER_PORT}",
        "--env=K_REVISION=container-smoke",
        "--env=SPHEREX_OUTPUT_DIR=/fixtures",
        f"--mount=type=bind,source={FIXTURE_DIR},target=/fixtures,readonly",
        image,
    )

    def verify() -> None:
        docker("exec", "-i", container, "python", "-", input_text=VERIFY_HTTP)

    def stop() -> None:
        docker("stop", "--time=10", container)
        exit_code = docker("inspect", "--format={{.State.ExitCode}}", container)
        assert exit_code in {"0", "143"}, f"Server exited with status {exit_code}"

    try:
        verify()
        print(docker("stats", "--no-stream", "--format={{.MemUsage}}", container), flush=True)
        stop()
        docker("start", container)
        verify()
        stop()
        log_counts = docker("logs", container).count("Application shutdown complete.")
        assert log_counts == 2, "Expected graceful server shutdown before and after restart"
    finally:
        docker("rm", "--force", container)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Local ingestion API image tag")
    smoke(parser.parse_args().image)


if __name__ == "__main__":
    main()
