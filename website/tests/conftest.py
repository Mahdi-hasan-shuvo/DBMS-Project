import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Keep the import-time app (app.py builds one at module level) away from the real database.
_SESSION_DIR = tempfile.mkdtemp(prefix="pharmacare_tests_")
os.environ["SQLITE_PATH"] = os.path.join(_SESSION_DIR, "import_time.db")
os.environ["DB_ENGINE"] = "sqlite"
os.environ["AUTO_INIT_DB"] = "0"

from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from db import Database  # noqa: E402
from seed import seed_demo_data  # noqa: E402


def _cfg(path):
    cfg = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}
    cfg.update(DB_ENGINE="sqlite", SQLITE_PATH=path)
    return cfg


@pytest.fixture(scope="session")
def seeded_template():
    """Seed once per test session; each test gets a fresh copy of this file."""
    path = os.path.join(_SESSION_DIR, "template.db")
    db = Database(_cfg(path))
    db.init_schema()
    seed_demo_data(db)
    db.close()
    yield path
    shutil.rmtree(_SESSION_DIR, ignore_errors=True)


@pytest.fixture
def db_path(seeded_template, tmp_path):
    path = str(tmp_path / "test.db")
    shutil.copy(seeded_template, path)
    return path


@pytest.fixture
def app(db_path):
    return create_app({"TESTING": True, "SQLITE_PATH": db_path, "AUTO_INIT_DB": False})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(db_path):
    database = Database(_cfg(db_path))
    yield database
    database.close()


@pytest.fixture
def empty_app(tmp_path):
    """App on a database with tables but no rows."""
    path = str(tmp_path / "empty.db")
    database = Database(_cfg(path))
    database.init_schema()
    database.close()
    return create_app({"TESTING": True, "SQLITE_PATH": path, "AUTO_INIT_DB": False})
