import datetime

from flask import Blueprint, current_app, render_template, request

from db import get_db
from utils import LIKE_ESCAPE, like

bp = Blueprint("dashboard", __name__)


def _day_bounds(day):
    nxt = day + datetime.timedelta(days=1)
    return f"{day.isoformat()} 00:00:00", f"{nxt.isoformat()} 00:00:00"


@bp.route("/")
def index():
    db = get_db()
    today = datetime.date.today()
    soon = (today + datetime.timedelta(days=current_app.config["EXPIRY_SOON_DAYS"])).isoformat()
    t0, t1 = _day_bounds(today)
    y0, _ = _day_bounds(today - datetime.timedelta(days=1))

    sales_today = db.one(
        "SELECT COUNT(*) AS txns, COALESCE(SUM(total_amount), 0) AS revenue "
        "FROM sales WHERE sale_date >= ? AND sale_date < ?", (t0, t1))
    revenue_yesterday = db.scalar(
        "SELECT COALESCE(SUM(total_amount), 0) FROM sales WHERE sale_date >= ? AND sale_date < ?",
        (y0, t0), 0)
    change = None
    if revenue_yesterday:
        change = (sales_today["revenue"] - revenue_yesterday) / revenue_yesterday * 100

    stats = db.one(
        "SELECT "
        " (SELECT COUNT(*) FROM medicines) AS medicines,"
        " (SELECT COALESCE(SUM(stock_quantity), 0) FROM medicines) AS units,"
        " (SELECT COUNT(*) FROM categories) AS categories,"
        " (SELECT COUNT(*) FROM suppliers WHERE status = 'Active') AS active_suppliers,"
        " (SELECT COUNT(*) FROM purchases WHERE status = 'Draft') AS draft_orders,"
        " (SELECT COUNT(*) FROM customers) AS customers,"
        " (SELECT COUNT(*) FROM customers WHERE created_at >= ?) AS new_customers,"
        " (SELECT COUNT(*) FROM medicines WHERE stock_quantity <= reorder_level AND expiry_date >= ?) AS low_stock,"
        " (SELECT COUNT(*) FROM medicines WHERE expiry_date >= ? AND expiry_date <= ?) AS expiring,"
        " (SELECT COUNT(*) FROM medicines WHERE expiry_date < ?) AS expired",
        ((today - datetime.timedelta(days=7)).isoformat(), today.isoformat(),
         today.isoformat(), soon, today.isoformat()),
    )

    # Last 7 days revenue split into prescription (Rx) vs over-the-counter (OTC)
    start7 = today - datetime.timedelta(days=6)
    rows = db.query(
        "SELECT DATE(sale_date) AS sale_day, "
        " SUM(CASE WHEN prescription_ref IS NOT NULL THEN total_amount ELSE 0 END) AS rx, "
        " SUM(CASE WHEN prescription_ref IS NULL THEN total_amount ELSE 0 END) AS otc, "
        " COUNT(*) AS txns "
        "FROM sales WHERE sale_date >= ? AND sale_date < ? "
        "GROUP BY DATE(sale_date) ORDER BY sale_day",
        (f"{start7.isoformat()} 00:00:00", t1),
    )
    by_day = {r["sale_day"]: r for r in rows}
    chart = []
    for i in range(7):
        d = start7 + datetime.timedelta(days=i)
        r = by_day.get(d.isoformat(), {})
        chart.append({"label": "Today" if d == today else d.strftime("%a"),
                      "rx": round(r.get("rx") or 0, 2), "otc": round(r.get("otc") or 0, 2),
                      "txns": r.get("txns") or 0})
    week_total = sum(c["rx"] + c["otc"] for c in chart)
    week_txns = sum(c["txns"] for c in chart)
    rx_share = (sum(c["rx"] for c in chart) / week_total * 100) if week_total else 0

    recent_sales = db.query(
        "SELECT s.sale_id, s.invoice_no, s.sale_date, s.total_amount, s.payment_method, "
        "       s.prescription_ref, c.customer_name, c.customer_id, "
        "       (SELECT COALESCE(SUM(si.quantity), 0) FROM sale_items si WHERE si.sale_id = s.sale_id) AS item_units "
        "FROM sales s LEFT JOIN customers c ON c.customer_id = s.customer_id "
        "ORDER BY s.sale_date DESC, s.sale_id DESC LIMIT 5")
    recent_purchases = db.query(
        "SELECT p.purchase_id, p.po_number, p.purchase_date, p.total_amount, p.status, sp.supplier_name "
        "FROM purchases p JOIN suppliers sp ON sp.supplier_id = p.supplier_id "
        "ORDER BY p.purchase_date DESC, p.purchase_id DESC LIMIT 5")
    low_stock = db.query(
        "SELECT medicine_id, medicine_name, generic_name, sku, stock_quantity, reorder_level "
        "FROM medicines WHERE stock_quantity <= reorder_level AND expiry_date >= ? "
        "ORDER BY stock_quantity * 1.0 / (reorder_level + 1), medicine_name LIMIT 5", (today.isoformat(),))
    expiring = db.query(
        "SELECT medicine_id, medicine_name, batch_no, expiry_date, stock_quantity "
        "FROM medicines WHERE expiry_date <= ? ORDER BY expiry_date LIMIT 5", (soon,))

    quick_customers = db.query("SELECT customer_id, customer_name FROM customers ORDER BY customer_name")
    quick_medicines = db.query(
        "SELECT medicine_id, medicine_name, price, stock_quantity FROM medicines "
        "WHERE stock_quantity > 0 AND expiry_date >= ? ORDER BY medicine_name", (today.isoformat(),))

    return render_template(
        "dashboard.html", sales_today=sales_today, change=change, stats=stats, chart=chart,
        week_total=week_total, avg_ticket=(week_total / week_txns if week_txns else 0), rx_share=rx_share,
        recent_sales=recent_sales, recent_purchases=recent_purchases, low_stock=low_stock,
        expiring=expiring, quick_customers=quick_customers, quick_medicines=quick_medicines,
    )


@bp.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    results = {"medicines": [], "customers": [], "suppliers": [], "sales": []}
    if q:
        db = get_db()
        pat = like(q)
        results["medicines"] = db.query(
            "SELECT m.medicine_id, m.medicine_name, m.generic_name, m.sku, m.stock_quantity, m.price, "
            "c.category_name FROM medicines m JOIN categories c ON c.category_id = m.category_id "
            "WHERE m.medicine_name LIKE ?" + LIKE_ESCAPE + " OR m.generic_name LIKE ?" + LIKE_ESCAPE +
            " OR m.sku LIKE ?" + LIKE_ESCAPE + " OR m.batch_no LIKE ?" + LIKE_ESCAPE +
            " ORDER BY m.medicine_name LIMIT 20", (pat, pat, pat, pat))
        results["customers"] = db.query(
            "SELECT customer_id, customer_name, phone, email, city FROM customers "
            "WHERE customer_name LIKE ?" + LIKE_ESCAPE + " OR phone LIKE ?" + LIKE_ESCAPE +
            " OR email LIKE ?" + LIKE_ESCAPE + " ORDER BY customer_name LIMIT 20", (pat, pat, pat))
        results["suppliers"] = db.query(
            "SELECT supplier_id, supplier_name, contact_person, phone, city FROM suppliers "
            "WHERE supplier_name LIKE ?" + LIKE_ESCAPE + " OR contact_person LIKE ?" + LIKE_ESCAPE +
            " OR phone LIKE ?" + LIKE_ESCAPE + " ORDER BY supplier_name LIMIT 20", (pat, pat, pat))
        results["sales"] = db.query(
            "SELECT s.sale_id, s.invoice_no, s.sale_date, s.total_amount, c.customer_name "
            "FROM sales s LEFT JOIN customers c ON c.customer_id = s.customer_id "
            "WHERE s.invoice_no LIKE ?" + LIKE_ESCAPE + " OR s.prescription_ref LIKE ?" + LIKE_ESCAPE +
            " ORDER BY s.sale_date DESC LIMIT 20", (pat, pat))
    total = sum(len(v) for v in results.values())
    return render_template("search.html", q=q, results=results, total=total)
