"""CLI must not run a 2016-2025 fit."""

from __future__ import annotations

import subprocess
import sys


def test_module_cli_is_a_noop() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "models.rush_yards"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "will not fit 2016-2025" in result.stdout
    assert "nflverse" in result.stdout
