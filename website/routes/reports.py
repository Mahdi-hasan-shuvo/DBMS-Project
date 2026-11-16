import datetime

from flask import Blueprint, current_app, render_template, request

from db import get_db
from utils import csv_response

bp = Blueprint("reports", __name__, url_prefix="/reports")

TABS = {
    "sales": "Sales & Revenue",
    "purchases": "Purchases & Suppliers",
    "inventory": "Inventory Valuation",
    "stock": "Low Stock & Expiry",
}

SALES_BY_PERIOD_SQL = """SELECT SUBSTR(s.sale_date, 1, {width}) AS bucket,
       COUNT(DISTINCT s.sale_id)            AS tx_count,
       SUM(si.quantity)                     AS units_sold,
       SUM(si.quantity * si.unit_price)     AS gross_revenue,
       SUM(si.quantity * m.cost_price)      AS cogs,
       SUM(si.quantity * si.unit_price) - SUM(si.quantity * m.cost_price) AS gross_profit
FROM sales s
JOIN sale_items si ON si.sale_id = s.sale_id
JOIN medicines m   ON m.medicine_id = si.medicine_id
WHERE s.sale_date >= ? AND s.sale_date < ?
GROUP BY SUBSTR(s.sale_date, 1, {width})
ORDER BY bucket DESC"""

TOP_MEDICINES_SQL = """SELECT m.medicine_id, m.medicine_name, m.generic_name, m.dosage_form,
       SUM(si.quantity) AS units, SUM(si.quantity * si.unit_price) AS revenue
FROM sale_items si
JOIN sales s     ON s.sale_id = si.sale_id
JOIN medicines m ON m.medicine_id = si.medicine_id
WHERE s.sale_date >= ? AND s.sale_date < ?
GROUP BY m.medicine_id, m.medicine_name, m.generic_name, m.dosage_form
ORDER BY units DESC
LIMIT 5"""

PURCHASES_BY_SUPPLIER_SQL = """SELECT sp.supplier_id, sp.supplier_name,
       COUNT(DISTINCT p.purchase_id)     AS orders,
       SUM(pi.quantity)                  AS units,
       SUM(pi.quantity * pi.unit_price)  AS goods_value
FROM purchases p
JOIN suppliers sp      ON sp.supplier_id = p.supplier_id
JOIN purchase_items pi ON pi.purchase_id = p.purchase_id
WHERE p.status = 'Received' AND p.purchase_date >= ? AND p.purchase_date <= ?
GROUP BY sp.supplier_id, sp.supplier_name
ORDER BY goods_value DESC"""

VALUATION_SQL = """SELECT c.category_id, c.category_name,
       COUNT(m.medicine_id)                          AS skus,
       COALESCE(SUM(m.stock_quantity), 0)            AS units,
       COALESCE(SUM(m.stock_quantity * m.cost_price), 0) AS cost_value,
       COALESCE(SUM(m.stock_quantity * m.price), 0)      AS retail_value
FROM categories c
LEFT JOIN medicines m ON m.category_id = c.category_id
GROUP BY c.category_id, c.category_name
ORDER BY cost_value DESC"""


def _range():
    today = datetime.date.today()
    preset = request.args.get("preset", "month")
    start = end = None
    if preset == "today":
        start = end = today
    elif preset == "week":
        start, end = today - datetime.timedelta(days=6), today
    elif preset == "quarter":
        start, end = today - datetime.timedelta(days=89), today
    elif preset == "custom":
        try:
            start = datetime.date.fromisoformat(request.args.get("start", ""))
            end = datetime.date.fromisoformat(request.args.get("end", ""))
        except ValueError:
            preset = "month"
        else:
            if start > end:
                start, end = end, start
    if start is None:
        preset = "month"
        start, end = today.replace(day=1), today
    return preset, start, end


def _bounds(start, end):
    return f"{start.isoformat()} 00:00:00", f"{(end + datetime.timedelta(days=1)).isoformat()} 00:00:00"


def sales_report(db, start, end, group):
    width = 7 if group == "month" else 10
    lo, hi = _bounds(start, end)
    sql = SALES_BY_PERIOD_SQL.format(width=width)
    periods = db.query(sql, (lo, hi))
    # Tax and discounts live on the sales header, so aggregate them separately to avoid double counting
    header = {r["bucket"]: r for r in db.query(
        f"SELECT SUBSTR(sale_date, 1, {width}) AS bucket, SUM(tax_amount) AS tax, "
        f"       SUM(discount_amount) AS discount, SUM(total_amount) AS collected "
        f"FROM sales WHERE sale_date >= ? AND sale_date < ? GROUP BY SUBSTR(sale_date, 1, {width})", (lo, hi))}
    for p in periods:
        h = header.get(p["bucket"], {})
        p["tax"] = h.get("tax") or 0
        p["discount"] = h.get("discount") or 0
        p["collected"] = h.get("collected") or 0
        p["margin_pct"] = (p["gross_profit"] / p["gross_revenue"] * 100) if p["gross_revenue"] else 0
    totals = {
        "tx_count": sum(p["tx_count"] for p in periods),
        "units": sum(p["units_sold"] or 0 for p in periods),
        "gross": sum(p["gross_revenue"] or 0 for p in periods),
        "cogs": sum(p["cogs"] or 0 for p in periods),
        "profit": sum(p["gross_profit"] or 0 for p in periods),
        "tax": sum(p["tax"] for p in periods),
        "discount": sum(p["discount"] for p in periods),
        "collected": sum(p["collected"] for p in periods),
    }
    totals["margin_pct"] = (totals["profit"] / totals["gross"] * 100) if totals["gross"] else 0
    top = db.query(TOP_MEDICINES_SQL, (lo, hi))
    payments = db.query(
        "SELECT payment_method, COUNT(*) AS txns, SUM(total_amount) AS amount FROM sales "
        "WHERE sale_date >= ? AND sale_date < ? GROUP BY payment_method ORDER BY amount DESC", (lo, hi))
    by_category = db.query(
        "SELECT c.category_name, SUM(si.quantity * si.unit_price) AS revenue "
        "FROM sale_items si JOIN sales s ON s.sale_id = si.sale_id "
        "JOIN medicines m ON m.medicine_id = si.medicine_id "
        "JOIN categories c ON c.category_id = m.category_id "
        "WHERE s.sale_date >= ? AND s.sale_date < ? "
        "GROUP BY c.category_name ORDER BY revenue DESC", (lo, hi))
    return {"periods": periods, "totals": totals, "top": top, "payments": payments,
            "by_category": by_category, "sql": sql, "params": (lo, hi)}


def purchases_report(db, start, end):
    params = (start.isoformat(), end.isoformat())
    suppliers = db.query(PURCHASES_BY_SUPPLIER_SQL, params)
    orders = db.query(
        "SELECT p.purchase_id, p.po_number, p.purchase_date, p.status, p.total_amount, sp.supplier_name "
        "FROM purchases p JOIN suppliers sp ON sp.supplier_id = p.supplier_id "
        "WHERE p.purchase_date >= ? AND p.purchase_date <= ? ORDER BY p.purchase_date DESC, p.purchase_id DESC",
        params)
    top = db.query(
        "SELECT m.medicine_id, m.medicine_name, SUM(pi.quantity) AS units, "
        "       SUM(pi.quantity * pi.unit_price) AS spent "
        "FROM purchase_items pi JOIN purchases p ON p.purchase_id = pi.purchase_id "
        "JOIN medicines m ON m.medicine_id = pi.medicine_id "
        "WHERE p.status = 'Received' AND p.purchase_date >= ? AND p.purchase_date <= ? "
        "GROUP BY m.medicine_id, m.medicine_name ORDER BY units DESC LIMIT 5", params)
    received = [o for o in orders if o["status"] == "Received"]
    totals = {
        "orders": len(received),
        "drafts": len(orders) - len(received),
        "spent": sum(o["total_amount"] for o in received),
        "units": sum(s["units"] or 0 for s in suppliers),
        "suppliers": len(suppliers),
    }
    return {"suppliers": suppliers, "orders": orders, "top": top, "totals": totals,
            "sql": PURCHASES_BY_SUPPLIER_SQL, "params": params}


def inventory_report(db):
    rows = db.query(VALUATION_SQL)
    totals = {
        "skus": sum(r["skus"] for r in rows),
        "units": sum(r["units"] for r in rows),
        "cost": sum(r["cost_value"] for r in rows),
        "retail": sum(r["retail_value"] for r in rows),
    }
    totals["margin"] = totals["retail"] - totals["cost"]
    return {"rows": rows, "totals": totals, "sql": VALUATION_SQL, "params": ()}


def stock_report(db):
    today = datetime.date.today()
    watch = (today + datetime.timedelta(days=current_app.config["EXPIRY_WATCH_DAYS"])).isoformat()
    low_sql = ("SELECT m.medicine_id, m.medicine_name, c.category_name, m.stock_quantity, m.reorder_level, "
               "       m.reorder_level - m.stock_quantity AS deficit, m.cost_price "
               "FROM medicines m JOIN categories c ON c.category_id = m.category_id "
               "WHERE m.stock_quantity <= m.reorder_level ORDER BY m.stock_quantity, m.medicine_name")
    low = db.query(low_sql)
    expiry = db.query(
        "SELECT m.medicine_id, m.medicine_name, m.batch_no, m.expiry_date, m.stock_quantity, "
        "       m.stock_quantity * m.cost_price AS value_at_risk "
        "FROM medicines m WHERE m.expiry_date <= ? ORDER BY m.expiry_date", (watch,))
    totals = {
        "low": len(low),
        "out": sum(1 for r in low if r["stock_quantity"] == 0),
        "reorder_cost": sum(max(r["reorder_level"] * 3 - r["stock_quantity"], 0) * r["cost_price"] for r in low),
        "expiring": len(expiry),
        "value_at_risk": sum(r["value_at_risk"] for r in expiry),
        "expired": sum(1 for r in expiry if r["expiry_date"] < today.isoformat()),
    }
    return {"low": low, "expiry": expiry, "totals": totals, "sql": low_sql, "params": ()}


def _build(db, tab, start, end, group):
    if tab == "purchases":
        return purchases_report(db, start, end)
    if tab == "inventory":
        return inventory_report(db)
    if tab == "stock":
        return stock_report(db)
    return sales_report(db, start, end, group)


@bp.route("/")
def index():
    tab = request.args.get("tab", "sales")
    tab = tab if tab in TABS else "sales"
    group = "month" if request.args.get("group") == "month" else "day"
    preset, start, end = _range()
    data = _build(get_db(), tab, start, end, group)
    chart = []
    if tab == "sales":
        chart = [{"label": p["bucket"], "revenue": round(p["gross_revenue"] or 0, 2),
                  "profit": round(p["gross_profit"] or 0, 2)} for p in reversed(data["periods"])]
    return render_template("reports/index.html", tab=tab, tabs=TABS, preset=preset, start=start, end=end,
                           group=group, data=data, chart=chart)


@bp.route("/export.csv")
def export():
    tab = request.args.get("tab", "sales")
    group = "month" if request.args.get("group") == "month" else "day"
    _, start, end = _range()
    data = _build(get_db(), tab, start, end, group)
    if tab == "purchases":
        return csv_response(
            "purchase_report.csv", ["supplier", "orders", "units", "goods_value"],
            [[r["supplier_name"], r["orders"], r["units"], round(r["goods_value"] or 0, 2)]
             for r in data["suppliers"]])
    if tab == "inventory":
        return csv_response(
            "inventory_valuation.csv", ["category", "skus", "units", "cost_value", "retail_value"],
            [[r["category_name"], r["skus"], r["units"], round(r["cost_value"], 2), round(r["retail_value"], 2)]
             for r in data["rows"]])
    if tab == "stock":
        return csv_response(
            "low_stock_report.csv", ["medicine", "category", "stock_quantity", "reorder_level", "deficit"],
            [[r["medicine_name"], r["category_name"], r["stock_quantity"], r["reorder_level"], r["deficit"]]
             for r in data["low"]])
    return csv_response(
        "sales_report.csv",
        ["period", "transactions", "units", "gross_revenue", "cogs", "gross_profit", "discount", "tax",
         "collected"],
        [[p["bucket"], p["tx_count"], p["units_sold"], round(p["gross_revenue"] or 0, 2),
          round(p["cogs"] or 0, 2), round(p["gross_profit"] or 0, 2), round(p["discount"], 2),
          round(p["tax"], 2), round(p["collected"], 2)] for p in data["periods"]])
