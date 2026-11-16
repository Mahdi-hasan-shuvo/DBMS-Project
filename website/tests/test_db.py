"""Database layer: dialect translation, script splitting, LIKE escaping, constraints."""
import decimal
import datetime

import pytest

from db import Database, IntegrityError, _normalize_value, split_sql
from utils import LIKE_ESCAPE, like


class FakeMySQL(Database):
    def __init__(self):  # no connection needed to test SQL rewriting
        self.engine = "mysql"


def test_placeholders_rewritten_for_mysql():
    db = FakeMySQL()
    sql = "SELECT * FROM t WHERE a = ? AND b LIKE ? ESCAPE '!' AND c = '100%'"
    assert db._sql(sql) == "SELECT * FROM t WHERE a = %s AND b LIKE %s ESCAPE '!' AND c = '100%%'"
    assert db.for_update() == " FOR UPDATE"


def test_normalize_mysql_types():
    assert _normalize_value(decimal.Decimal("14.20")) == 14.2
    assert _normalize_value(decimal.Decimal("3")) == 3 and isinstance(_normalize_value(decimal.Decimal("3")), int)
    assert _normalize_value(datetime.date(2026, 1, 2)) == "2026-01-02"
    assert _normalize_value(datetime.datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02 03:04:05"


def test_split_sql_handles_quotes_and_comments():
    script = "-- comment; ignored\nCREATE TABLE a (x VARCHAR(5) DEFAULT 'a;b');\n\nINSERT INTO a VALUES ('it''s;');\nSELECT 1"
    parts = split_sql(script)
    assert len(parts) == 3
    assert parts[0].startswith("CREATE TABLE a") and "'a;b'" in parts[0]
    assert parts[2] == "SELECT 1"


def test_mysql_schema_splits_into_expected_statements():
    with open("database/schema_mysql.sql", encoding="utf-8") as fh:
        parts = split_sql(fh.read())
    creates = [p for p in parts if p.upper().startswith("CREATE TABLE")]
    assert len(creates) == 8
    assert all("ENGINE=InnoDB" in p for p in creates)


def test_like_escaping_matches_literally(db):
    db.execute("INSERT INTO categories (category_name) VALUES (?)", ("100% Natural_Herbs",))
    db.execute("INSERT INTO categories (category_name) VALUES (?)", ("1000 Naturalx Herbs",))
    rows = db.query("SELECT category_name FROM categories WHERE category_name LIKE ?" + LIKE_ESCAPE,
                    (like("100% Natural_"),))
    assert [r["category_name"] for r in rows] == ["100% Natural_Herbs"]


def test_check_constraint_blocks_negative_stock(db):
    with pytest.raises(IntegrityError):
        db.execute("UPDATE medicines SET stock_quantity = -1 WHERE medicine_id = 1")


def test_foreign_keys_enforced(db):
    with pytest.raises(IntegrityError):
        db.execute("INSERT INTO sale_items (sale_id, medicine_id, quantity, unit_price) VALUES (999999, 1, 1, 1)")
    with pytest.raises(IntegrityError):
        db.execute("DELETE FROM suppliers WHERE supplier_id = (SELECT supplier_id FROM purchases LIMIT 1)")


def test_transaction_rollback(db):
    before = db.scalar("SELECT COUNT(*) FROM categories")
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute("INSERT INTO categories (category_name) VALUES ('Temp A')")
            db.execute("INSERT INTO categories (category_name) VALUES ('Temp B')")
            raise RuntimeError("boom")
    assert db.scalar("SELECT COUNT(*) FROM categories") == before
