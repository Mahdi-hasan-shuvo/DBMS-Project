"""Application settings.

Values come from environment variables, optionally loaded from a `.env` file
next to this module (simple KEY=VALUE lines, `#` comments allowed).
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "pharmacare-dev-secret-change-me")

    # "sqlite" (default, zero setup) or "mysql" (XAMPP / MySQL / MariaDB)
    DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").lower()
    SQLITE_PATH = os.environ.get(
        "SQLITE_PATH", os.path.join(BASE_DIR, "instance", "pharmacy_management.db")
    )
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "pharmacy_management")

    # Create tables and load demo data automatically when the database is empty
    AUTO_INIT_DB = os.environ.get("AUTO_INIT_DB", "1") == "1"

    CURRENCY = os.environ.get("CURRENCY", "$")
    TAX_RATE = float(os.environ.get("TAX_RATE", "0.05"))
    EXPIRY_SOON_DAYS = int(os.environ.get("EXPIRY_SOON_DAYS", "30"))
    EXPIRY_WATCH_DAYS = int(os.environ.get("EXPIRY_WATCH_DAYS", "90"))
    PER_PAGE = int(os.environ.get("PER_PAGE", "10"))
    PHARMACY_NAME = os.environ.get("PHARMACY_NAME", "PharmaCare DBMS")
