"""The guard this covers protects the key that encrypts provider credentials. It used to
be disabled by the exact configuration we deploy (LOCAL_MODE pins ENVIRONMENT=development),
so a host with no .env would boot happily on the repo's published key."""

import os
import subprocess
import sys

from app.core.config import DEFAULT_SECRET_KEY

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _boot(secret_key: str) -> subprocess.CompletedProcess:
    # A subprocess, because the guard runs at import time and app.main is already imported
    # in this process. An explicit env var also outranks any value in backend/.env.
    env = {**os.environ, "APP_SECRET_KEY": secret_key, "ENVIRONMENT": "development"}
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        check=False,
    )


def test_default_secret_key_refuses_to_boot_even_in_development():
    result = _boot(DEFAULT_SECRET_KEY)
    assert result.returncode != 0
    assert b"APP_SECRET_KEY" in result.stderr


def test_a_real_secret_key_boots():
    result = _boot("a-real-key-that-is-definitely-not-the-default")
    assert result.returncode == 0, result.stderr.decode()
