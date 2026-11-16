import datetime
import os

from flask import Blueprint, Response, current_app, render_template

from db import SCHEMA_DIR, get_db

bp = Blueprint("system", __name__, url_prefix="/database")

# Parent tables first so the backup restores without foreign key errors
TABLES = ["categories", "suppliers", "customers", "medicines", "purchases", "purchase_items", "sales",
          "sale_items"]
TABLE_INFO = {
    "categories": ("category_id", "Medicine categories", []),
    "suppliers": ("supplier_id", "Supplier contact and terms", []),
    "customers": ("customer_id", "Customer / patient records", []),
    "medicines": ("medicine_id", "Medicine details, price, stock and expiry",
                  [("category_id", "categories", "RESTRICT")]),
    "purchases": ("purchase_id", "Purchase orders (header)", [("supplier_id", "suppliers", "RESTRICT")]),
    "purchase_items": ("purchase_item_id", "Medicines in each purchase",
                       [("purchase_id", "purchases", "CASCADE"), ("medicine_id", "medicines", "RESTRICT")]),
    "sales": ("sale_id", "Sales / bills (header)", [("customer_id", "customers", "RESTRICT")]),
    "sale_items": ("sale_item_id", "Medicines in each sale",
                   [("sale_id", "sales", "CASCADE"), ("medicine_id", "medicines", "RESTRICT")]),
}


@bp.route("/")
def index():
    db = get_db()
    tables = []
    for name in TABLES:
        pk, purpose, fks = TABLE_INFO[name]
        tables.append({"name": name, "pk": pk, "purpose": purpose, "fks": fks,
                       "rows": db.scalar(f"SELECT COUNT(*) FROM {name}", (), 0)})
    schema_file = "schema_mysql.sql" if db.is_mysql else "schema_sqlite.sql"
    with open(os.path.join(SCHEMA_DIR, "schema_mysql.sql"), encoding="utf-8") as fh:
        schema_sql = fh.read()
    # Integrity check: stock must equal received purchases minus sales for every medicine
    mismatches = db.query(
        "SELECT m.medicine_id, m.medicine_name, m.stock_quantity, "
        "       COALESCE(pin.qty, 0) - COALESCE(pout.qty, 0) AS expected "
        "FROM medicines m "
        "LEFT JOIN (SELECT pi.medicine_id, SUM(pi.quantity) AS qty FROM purchase_items pi "
        "           JOIN purchases p ON p.purchase_id = pi.purchase_id WHERE p.status = 'Received' "
        "           GROUP BY pi.medicine_id) pin ON pin.medicine_id = m.medicine_id "
        "LEFT JOIN (SELECT medicine_id, SUM(quantity) AS qty FROM sale_items GROUP BY medicine_id) pout "
        "       ON pout.medicine_id = m.medicine_id "
        "WHERE m.stock_quantity <> COALESCE(pin.qty, 0) - COALESCE(pout.qty, 0)")
    cfg = current_app.config
    if db.is_mysql:
        connection = f"{cfg['MYSQL_USER']}@{cfg['MYSQL_HOST']}:{cfg['MYSQL_PORT']}/{cfg['MYSQL_DATABASE']}"
    else:
        try:
            connection = os.path.relpath(cfg["SQLITE_PATH"], os.path.dirname(SCHEMA_DIR))
        except ValueError:  # different drive on Windows
            connection = cfg["SQLITE_PATH"]
    return render_template("system/index.html", tables=tables, schema_sql=schema_sql, schema_file=schema_file,
                           mismatches=mismatches, connection=connection)


def _sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def build_dump(db):
    """MySQL-compatible SQL dump: schema + INSERT statements for every table."""
    with open(os.path.join(SCHEMA_DIR, "schema_mysql.sql"), encoding="utf-8") as fh:
        schema = fh.read()
    out = [
        "-- PharmaCare DBMS backup",
        f"-- Generated {datetime.datetime.now():%Y-%m-%d %H:%M:%S} from {db.engine}",
        "-- Import into MySQL/MariaDB (e.g. phpMyAdmin > Import) to restore.",
        "",
        "CREATE DATABASE IF NOT EXISTS pharmacy_management CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;",
        "USE pharmacy_management;",
        "",
        schema,
        "",
        "SET FOREIGN_KEY_CHECKS = 0;",
    ]
    for table in TABLES:
        rows = db.query(f"SELECT * FROM {table} ORDER BY {TABLE_INFO[table][0]}")
        if not rows:
            continue
        cols = list(rows[0].keys())
        out.append(f"\n-- {table}: {len(rows)} rows")
        for i in range(0, len(rows), 200):
            chunk = rows[i:i + 200]
            values = ",\n".join("(" + ", ".join(_sql_literal(r[c]) for c in cols) + ")" for r in chunk)
            out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{values};")
    out.append("\nSET FOREIGN_KEY_CHECKS = 1;\n")
    return "\n".join(out)


@bp.route("/backup.sql")
def backup():
    dump = build_dump(get_db())
    name = f"pharmacy_management_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.sql"
    return Response(dump, mimetype="application/sql",
                    headers={"Content-Disposition": f"attachment; filename={name}"})
