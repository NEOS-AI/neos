import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "neos.api.dependencies.auth",
        "neos.api.dependencies.resource_access",
    ],
)
def test_dependency_module_imports_without_google_api_key(module_name):
    env = os.environ.copy()
    env.pop("GOOGLE_API_KEY", None)
    env["JWT_SECRET_KEY"] = "neos-test-only-secret-key-2026-07-01"

    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
