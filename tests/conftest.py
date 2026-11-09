import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def api():
    """The API module (imported once: it loads models and data files)."""
    from api import main
    return main


@pytest.fixture(scope="session")
def client(api):
    """HTTP client for the API. Startup tasks (cache warm-up) don't run: no `with` block."""
    from fastapi.testclient import TestClient
    return TestClient(api.app)
