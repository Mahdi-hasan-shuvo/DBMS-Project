"""Thin database layer that runs the same SQL on SQLite and MySQL/MariaDB.

All SQL in the app is written with `?` placeholders and portable syntax.
For MySQL the placeholders are rewritten to `%s` (PyMySQL paramstyle).
Rows are returned as plain dicts; DECIMAL values become float and
DATE/DATETIME values become ISO strings so both engines look identical
to the rest of the code.
"""
import datetime
import decimal
import os
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database")


class DBError(Exception):
    """Generic database failure."""


class IntegrityError(DBError):
    """Constraint violation: FK, UNIQUE, NOT NULL or CHECK."""


class ExecResult:
    def __init__(self, lastrowid, rowcount):
        self.lastrowid = lastrowid
        self.rowcount = rowcount


def _normalize_value(value):
    if isinstance(value, decimal.Decimal):
        # MySQL returns SUM()/DECIMAL as Decimal: whole numbers become int (counts), others float
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _normalize_row(row):
    return {k: _normalize_value(v) for k, v in row.items()}


def _sqlite_dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


# MySQL/MariaDB error codes that mean "a constraint rejected the change"
_MYSQL_CONSTRAINT_CODES = {1048, 1062, 1216, 1217, 1451, 1452, 3819, 4025}


class Database:
    def __init__(self, cfg):
        self.engine = cfg["DB_ENGINE"]
        if self.engine not in ("sqlite", "mysql"):
            raise DBError(f"Unsupported DB_ENGINE '{self.engine}' (use sqlite or mysql)")
        self.cfg = cfg
        self._depth = 0
        self.conn = self._connect()

    # ------------------------------------------------------------------ setup
    def _connect(self):
        if self.engine == "mysql":
            import pymysql

            self._driver = pymysql
            params = dict(
                host=self.cfg["MYSQL_HOST"],
                port=self.cfg["MYSQL_PORT"],
                user=self.cfg["MYSQL_USER"],
                password=self.cfg["MYSQL_PASSWORD"],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
            name = self.cfg["MYSQL_DATABASE"]
            try:
                return pymysql.connect(database=name, **params)
            except pymysql.err.OperationalError as exc:
                if not exc.args or exc.args[0] != 1049:  # 1049 = unknown database
                    raise DBError(f"Cannot connect to MySQL: {exc}") from exc
            # First run on a fresh XAMPP install: create the database, then connect to it
            if not name.replace("_", "").isalnum():
                raise DBError(f"Invalid MYSQL_DATABASE name '{name}'")
            server = pymysql.connect(**params)
            try:
                with server.cursor() as cur:
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` "
                                "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
                server.commit()
            finally:
                server.close()
            return pymysql.connect(database=name, **params)
        self._driver = sqlite3
        path = self.cfg["SQLITE_PATH"]
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = _sqlite_dict_factory
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @property
    def is_mysql(self):
        return self.engine == "mysql"

    def for_update(self):
        """Row-lock suffix for SELECTs inside a transaction (MySQL InnoDB only)."""
        return " FOR UPDATE" if self.is_mysql else ""

    def _sql(self, sql):
        if self.is_mysql:
            return sql.replace("%", "%%").replace("?", "%s")
        return sql

    def _wrap_error(self, exc):
        if isinstance(exc, self._driver.IntegrityError):
            return IntegrityError(str(exc))
        if self.is_mysql:
            code = exc.args[0] if exc.args else None
            if code in _MYSQL_CONSTRAINT_CODES:
                return IntegrityError(str(exc))
        return DBError(str(exc))

    # ---------------------------------------------------------------- queries
    def _run(self, sql, params=()):
        cur = self.conn.cursor()
        try:
            cur.execute(self._sql(sql), tuple(params))
        except self._driver.Error as exc:
            cur.close()
            raise self._wrap_error(exc) from exc
        return cur

    def query(self, sql, params=()):
        cur = self._run(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [_normalize_row(r) for r in rows]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql, params=(), default=None):
        row = self.one(sql, params)
        if not row:
            return default
        value = next(iter(row.values()))
        return default if value is None else value

    def execute(self, sql, params=()):
        """Run a write statement. Commits immediately unless inside transaction()."""
        cur = self._run(sql, params)
        result = ExecResult(cur.lastrowid, cur.rowcount)
        cur.close()
        if self._depth == 0:
            self.conn.commit()
        return result

    @contextmanager
    def transaction(self):
        """Group several writes into one atomic unit (nested calls join the outer one)."""
        if self._depth == 0 and self.is_mysql:
            self.conn.begin()
        self._depth += 1
        try:
            yield self
        except Exception:
            self._depth -= 1
            if self._depth == 0:
                self.conn.rollback()
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                try:
                    self.conn.commit()
                except self._driver.Error as exc:
                    self.conn.rollback()
                    raise self._wrap_error(exc) from exc

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ----------------------------------------------------------------- schema
    def table_exists(self, name):
        if self.is_mysql:
            return bool(self.scalar(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = ?", (name,), 0))
        return bool(self.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?", (name,), 0))

    def run_script(self, path):
        with open(path, encoding="utf-8") as fh:
            script = fh.read()
        if not self.is_mysql:
            self.conn.executescript(script)
            self.conn.commit()
            return
        cur = self.conn.cursor()
        try:
            for statement in split_sql(script):
                cur.execute(statement)
            self.conn.commit()
        finally:
            cur.close()

    def init_schema(self):
        name = "schema_mysql.sql" if self.is_mysql else "schema_sqlite.sql"
        self.run_script(os.path.join(SCHEMA_DIR, name))


def split_sql(script):
    """Split a plain SQL script on `;`, ignoring `--` comment lines and semicolons in quotes."""
    statements, buf, quote = [], [], None
    for line in script.splitlines():
        if quote is None and line.strip().startswith("--"):
            continue
        for ch in line:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"', "`"):
                quote = ch
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    statements.append(stmt)
                buf = []
                continue
            buf.append(ch)
        buf.append("\n")
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


# ------------------------------------------------------------- flask helpers
def _cfg():
    return current_app.config


def get_db():
    if "db" not in g:
        g.db = Database(_cfg())
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_database(app):
    """Create tables (and demo data) the first time the app starts on an empty database."""
    if not app.config.get("AUTO_INIT_DB"):
        return
    with app.app_context():
        try:
            db = Database(app.config)
        except DBError as exc:
            app.logger.warning("Database not available yet (%s). Start MySQL in XAMPP and reload.", exc)
            return
        try:
            if not db.table_exists("medicines"):
                db.init_schema()
                from seed import seed_demo_data

                seed_demo_data(db)
        finally:
            db.close()
