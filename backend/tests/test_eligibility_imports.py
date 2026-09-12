"""Fresh processes prevent pytest import order from masking package cycles."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "imports",
    [
        "from app.relevance.engine import FAMILIES; from app.eligibility import evaluate_job; import app.main",
        "from app.eligibility import evaluate_job; from app.relevance import analyze_relevance; import app.main",
        "import app.main; from app.jobs.orchestration import run_source_batched",
    ],
)
def test_public_imports_in_a_fresh_process(imports):
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", imports + "; print('IMPORT_OK')"],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend)},
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout
