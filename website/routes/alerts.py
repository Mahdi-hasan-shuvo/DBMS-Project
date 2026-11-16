import datetime

from flask import Blueprint, current_app, render_template, request

from db import get_db
from utils import LIKE_ESCAPE, csv_response, get_page, int_arg, like

bp = Blueprint("alerts", __name__, url_prefix="/alerts")

SEVERITIES = {
    "EXPIRED": "Expired",
    "OUT_OF_STOCK": "Out of stock",
    "LOW_STOCK": "Low stock",
    "EXPIRING_SOON": "Expiring soon",
    "EXPIRY_WATCH": "Expiry watch",
}

# The alert classification is done by the database with a CASE expression.
ALERT_SQL = """SELECT m.medicine_id, m.medicine_name, m.generic_name, m.dosage_form, m.sku,
       m.batch_no, m.stock_quantity, m.reorder_level, m.cost_price, m.expiry_date,
       c.category_id, c.category_name,
       CASE
           WHEN m.expiry_date < :today            THEN 'EXPIRED'
           WHEN m.stock_quantity = 0              THEN 'OUT_OF_STOCK'
           WHEN m.stock_quantity <= m.reorder_level THEN 'LOW_STOCK'
           WHEN m.expiry_date <= :soon            THEN 'EXPIRING_SOON'
           WHEN m.expiry_date <= :watch           THEN 'EXPIRY_WATCH'
           ELSE 'OK'
       END AS alert_status,
       CASE
           WHEN m.expiry_date < :today            THEN 1
           WHEN m.stock_quantity = 0              THEN 2
           WHEN m.stock_quantity <= m.reorder_level THEN 3
           WHEN m.expiry_date <= :soon            THEN 4
           ELSE 5
       END AS priority,
       (SELECT p.supplier_id FROM purchase_items pi
          JOIN purchases p ON p.purchase_id = pi.purchase_id
         WHERE pi.medicine_id = m.medicine_id
         ORDER BY p.purchase_date DESC, p.purchase_id DESC LIMIT 1) AS last_supplier_id,
       (SELECT s.supplier_name FROM purchase_items pi
          JOIN purchases p ON p.purchase_id = pi.purchase_id
          JOIN suppliers s ON s.supplier_id = p.supplier_id
         WHERE pi.medicine_id = m.medicine_id
         ORDER BY p.purchase_date DESC, p.purchase_id DESC LIMIT 1) AS last_supplier
FROM medicines m
JOIN categories c ON c.category_id = m.category_id
WHERE m.stock_quantity <= m.reorder_level OR m.expiry_date <= :watch"""


def _bound_sql(today, soon, watch):
    """Replace named markers with positional '?' and return (sql, params)."""
    sql, params = ALERT_SQL, []
    order = []
    i = 0
    while True:
        positions = {name: sql.find(f":{name}", i) for name in ("today", "soon", "watch")}
        positions = {k: v for k, v in positions.items() if v != -1}
        if not positions:
            break
        name = min(positions, key=positions.get)
        pos = positions[name]
        sql = sql[:pos] + "?" + sql[pos + len(name) + 1:]
        order.append(name)
        i = pos + 1
    values = {"today": today, "soon": soon, "watch": watch}
    params = [values[n] for n in order]
    return sql, params


def _query_parts():
    today = datetime.date.today()
    soon = (today + datetime.timedelta(days=current_app.config["EXPIRY_SOON_DAYS"])).isoformat()
    watch = (today + datetime.timedelta(days=current_app.config["EXPIRY_WATCH_DAYS"])).isoformat()
    inner, params = _bound_sql(today.isoformat(), soon, watch)

    where, outer = [], []
    tab = request.args.get("tab", "all")
    if tab == "stock":
        where.append("t.alert_status IN ('OUT_OF_STOCK', 'LOW_STOCK')")
    elif tab == "expiry":
        where.append("t.alert_status IN ('EXPIRED', 'EXPIRING_SOON', 'EXPIRY_WATCH')")
    severity = request.args.get("severity", "")
    if severity in SEVERITIES:
        where.append("t.alert_status = ?")
        outer.append(severity)
    category = int_arg("category")
    if category:
        where.append("t.category_id = ?")
        outer.append(category)
    q = (request.args.get("q") or "").strip()
    if q:
        pat = like(q)
        where.append("(t.medicine_name LIKE ?" + LIKE_ESCAPE + " OR t.generic_name LIKE ?" + LIKE_ESCAPE +
                     " OR t.sku LIKE ?" + LIKE_ESCAPE + " OR t.batch_no LIKE ?" + LIKE_ESCAPE + ")")
        outer += [pat, pat, pat, pat]
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"SELECT * FROM ({inner}) t{clause}"
    return base, params + outer, {"tab": tab, "severity": severity, "category": category, "q": q}


@bp.route("/")
def index():
    db = get_db()
    base, params, f = _query_parts()
    total = db.scalar(f"SELECT COUNT(*) FROM ({base}) x", params, 0)
    page = get_page(total)
    rows = db.query(base + " ORDER BY t.priority, t.expiry_date, t.medicine_name LIMIT ? OFFSET ?",
                    params + [page.per_page, page.offset])

    today = datetime.date.today()
    soon = (today + datetime.timedelta(days=current_app.config["EXPIRY_SOON_DAYS"])).isoformat()
    watch = (today + datetime.timedelta(days=current_app.config["EXPIRY_WATCH_DAYS"])).isoformat()
    kpi = db.one(
        "SELECT "
        " SUM(CASE WHEN stock_quantity > 0 AND stock_quantity <= reorder_level AND expiry_date >= ? THEN 1 ELSE 0 END) AS low,"
        " SUM(CASE WHEN stock_quantity > 0 AND stock_quantity <= reorder_level AND expiry_date >= ?"
        "          THEN reorder_level - stock_quantity ELSE 0 END) AS low_deficit,"
        " SUM(CASE WHEN stock_quantity = 0 AND expiry_date >= ? THEN 1 ELSE 0 END) AS out_of_stock,"
        " SUM(CASE WHEN expiry_date >= ? AND expiry_date <= ? THEN 1 ELSE 0 END) AS expiring,"
        " SUM(CASE WHEN expiry_date >= ? AND expiry_date <= ? THEN stock_quantity * cost_price ELSE 0 END) AS expiring_value,"
        " SUM(CASE WHEN expiry_date < ? THEN 1 ELSE 0 END) AS expired,"
        " SUM(CASE WHEN expiry_date < ? THEN stock_quantity * cost_price ELSE 0 END) AS expired_value "
        "FROM medicines",
        (today.isoformat(), today.isoformat(), today.isoformat(), today.isoformat(), watch,
         today.isoformat(), watch, today.isoformat(), today.isoformat()))
    tab_counts = db.one(
        f"SELECT COUNT(*) AS all_count, "
        f" SUM(CASE WHEN t.alert_status IN ('OUT_OF_STOCK', 'LOW_STOCK') THEN 1 ELSE 0 END) AS stock_count, "
        f" SUM(CASE WHEN t.alert_status IN ('EXPIRED', 'EXPIRING_SOON', 'EXPIRY_WATCH') THEN 1 ELSE 0 END) AS expiry_count "
        f"FROM ({_bound_sql(today.isoformat(), soon, watch)[0]}) t",
        _bound_sql(today.isoformat(), soon, watch)[1])
    categories = db.query("SELECT category_id, category_name FROM categories ORDER BY category_name")
    return render_template("alerts/index.html", rows=rows, page=page, f=f, kpi=kpi, tab_counts=tab_counts,
                           categories=categories, severities=SEVERITIES, alert_sql=ALERT_SQL,
                           watch_days=current_app.config["EXPIRY_WATCH_DAYS"])


@bp.route("/export.csv")
def export():
    base, params, _ = _query_parts()
    rows = get_db().query(base + " ORDER BY t.priority, t.expiry_date, t.medicine_name", params)
    return csv_response(
        "inventory_alerts.csv",
        ["medicine_id", "medicine_name", "category", "batch_no", "stock_quantity", "reorder_level",
         "expiry_date", "alert_status", "last_supplier"],
        [[r["medicine_id"], r["medicine_name"], r["category_name"], r["batch_no"], r["stock_quantity"],
          r["reorder_level"], r["expiry_date"], r["alert_status"], r["last_supplier"]] for r in rows],
    )
