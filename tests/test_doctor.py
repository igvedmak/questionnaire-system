"""Smoke test for `qst doctor`. Runs the actual self-test harness in a
subprocess and asserts it exits 0. This is the slowest test in the suite
(spawns a uvicorn subprocess); it gates the end-to-end story.

Marked ``slow`` so it can be excluded with ``pytest -m "not slow"`` for
fast inner-loop runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.slow
def test_doctor_passes(tmp_path: Path):
    """End-to-end: run `qst doctor` from a clean cwd and assert exit code 0."""
    proc = subprocess.run(
        [sys.executable, "-m", "questionnaire.cli.main", "doctor"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"qst doctor failed (exit {proc.returncode}):\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    # Sanity: the harness should report it ran multiple checks.
    assert "ALL GREEN" in proc.stdout, proc.stdout
