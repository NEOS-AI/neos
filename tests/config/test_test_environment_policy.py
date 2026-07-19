"""Contracts for deterministic process-wide pytest defaults."""

import os
import subprocess
import sys


def _run_bootstrap(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pytest_bootstrap_disables_remote_litellm_cost_map():
    result = _run_bootstrap(
        "import os, runpy; "
        "runpy.run_path('tests/conftest.py'); "
        "assert os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] == 'True'"
    )

    assert result.returncode == 0, result.stderr


def test_pytest_bootstrap_preserves_explicit_litellm_cost_map_setting():
    result = _run_bootstrap(
        "import os, runpy; "
        "os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'False'; "
        "runpy.run_path('tests/conftest.py'); "
        "assert os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] == 'False'"
    )

    assert result.returncode == 0, result.stderr
