import datetime

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   url_for)

from db import get_db
from services.inventory import PAYMENT_METHODS, InventoryError, create_sale
from utils import LIKE_ESCAPE, csv_response, get_page, like

bp = Blueprint("sales", __name__, url_prefix="/sales")

LIST_SQL = (
    "SELECT s.*, c.customer_name, "
    "       (SELECT COALESCE(SUM(si.quantity), 0) FROM sale_items si WHERE si.sale_id = s.sale_id) AS units, "
    "       (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id = s.sale_id) AS line_count "
    "FROM sales s LEFT JOIN customers c ON c.customer_id = s.customer_id"
)


def _today_stats(db):
    today = datetime.date.today()
    return db.one(
        "SELECT COUNT(*) AS txns, COALESCE(SUM(total_amount), 0) AS revenue, "
        "       COALESCE(SUM(CASE WHEN payment_method = 'Cash' THEN total_amount ELSE 0 END), 0) AS cash "
        "FROM sales WHERE sale_date >= ? AND sale_date < ?",
        (f"{today.isoformat()} 00:00:00", f"{(today + datetime.timedelta(days=1)).isoformat()} 00:00:00"))


@bp.route("/pos")
def pos():
    db = get_db()
    today = datetime.date.today().isoformat()
    medicines = db.query(
        "SELECT m.medicine_id, m.medicine_name, m.generic_name, m.dosage_form, m.sku, m.batch_no, m.price, "
        "       m.stock_quantity, m.reorder_level, m.expiry_date, c.category_id, c.category_name "
        "FROM medicines m JOIN categories c ON c.category_id = m.category_id ORDER BY m.medicine_name")
    for m in medicines:
        m["expired"] = m["expiry_date"] < today
    categories = db.query(
        "SELECT c.category_id, c.category_name, COUNT(m.medicine_id) AS n FROM categories c "
        "JOIN medicines m ON m.category_id = c.category_id "
        "GROUP BY c.category_id, c.category_name ORDER BY n DESC, c.category_name")
    customers = db.query(
        "SELECT customer_id, customer_name, phone, allergies, customer_type FROM customers ORDER BY customer_name")
    return render_template("sales/pos.html", medicines=medicines, categories=categories, customers=customers,
                           stats=_today_stats(db), payment_methods=PAYMENT_METHODS,
                           history_count=db.scalar("SELECT COUNT(*) FROM sales", (), 0))


@bp.route("/checkout", methods=["POST"])
def checkout():
    """JSON endpoint used by the POS screen."""
    payload = request.get_json(silent=True) or {}
    try:
        sale_id = create_sale(
            get_db(), payload.get("items") or [],
            customer_id=payload.get("customer_id") or None,
            payment_method=payload.get("payment_method") or "Cash",
            amount_paid=payload.get("amount_paid"),
            discount_percent=payload.get("discount_percent") or 0,
            prescription_ref=payload.get("prescription_ref"),
            tax_rate=current_app.config["TAX_RATE"],
        )
    except InventoryError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    return jsonify(ok=True, sale_id=sale_id, redirect=url_for("sales.invoice", sale_id=sale_id))


@bp.route("/quick", methods=["POST"])
def quick():
    """Single-item sale from the dashboard 'Quick Dispense' card."""
    form = request.form
    try:
        sale_id = create_sale(
            get_db(), [{"medicine_id": form.get("medicine_id"), "quantity": form.get("quantity")}],
            customer_id=form.get("customer_id") or None,
            payment_method=form.get("payment_method") or "Cash",
            tax_rate=current_app.config["TAX_RATE"],
        )
    except InventoryError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dashboard.index"))
    flash("Sale completed and stock updated.", "success")
    return redirect(url_for("sales.invoice", sale_id=sale_id))


def _filters():
    where, params = [], []
    q = (request.args.get("q") or "").strip()
    if q:
        pat = like(q)
        where.append("(s.invoice_no LIKE ?" + LIKE_ESCAPE + " OR c.customer_name LIKE ?" + LIKE_ESCAPE +
                     " OR s.prescription_ref LIKE ?" + LIKE_ESCAPE + ")")
        params += [pat, pat, pat]
    method = request.args.get("method", "")
    if method in PAYMENT_METHODS:
        where.append("s.payment_method = ?")
        params.append(method)
    start, end = request.args.get("start", ""), request.args.get("end", "")
    try:
        if start:
            where.append("s.sale_date >= ?")
            params.append(f"{datetime.date.fromisoformat(start).isoformat()} 00:00:00")
        if end:
            where.append("s.sale_date < ?")
            params.append(f"{(datetime.date.fromisoformat(end) + datetime.timedelta(days=1)).isoformat()} 00:00:00")
    except ValueError:
        abort(400)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params, {"q": q, "method": method, "start": start, "end": end}


@bp.route("/")
def index():
    db = get_db()
    clause, params, f = _filters()
    total = db.scalar("SELECT COUNT(*) FROM sales s LEFT JOIN customers c ON c.customer_id = s.customer_id"
                      + clause, params, 0)
    page = get_page(total)
    rows = db.query(f"{LIST_SQL}{clause} ORDER BY s.sale_date DESC, s.sale_id DESC LIMIT ? OFFSET ?",
                    params + [page.per_page, page.offset])
    summary = db.one(
        "SELECT COUNT(*) AS txns, COALESCE(SUM(s.total_amount), 0) AS revenue, "
        "       COALESCE(AVG(s.total_amount), 0) AS avg_ticket, COALESCE(SUM(s.discount_amount), 0) AS discounts "
        "FROM sales s LEFT JOIN customers c ON c.customer_id = s.customer_id" + clause, params)
    return render_template("sales/index.html", rows=rows, page=page, f=f, summary=summary,
                           stats=_today_stats(db), payment_methods=PAYMENT_METHODS)


@bp.route("/export.csv")
def export():
    clause, params, _ = _filters()
    rows = get_db().query(f"{LIST_SQL}{clause} ORDER BY s.sale_date DESC, s.sale_id DESC", params)
    return csv_response(
        "sales.csv",
        ["sale_id", "invoice_no", "sale_date", "customer", "lines", "units", "subtotal", "discount_amount",
         "tax_amount", "total_amount", "payment_method", "prescription_ref"],
        [[r["sale_id"], r["invoice_no"], r["sale_date"], r["customer_name"] or "Walk-in", r["line_count"],
          r["units"], r["subtotal"], r["discount_amount"], r["tax_amount"], r["total_amount"],
          r["payment_method"], r["prescription_ref"]] for r in rows],
    )


@bp.route("/<int:sale_id>")
def invoice(sale_id):
    db = get_db()
    sale = db.one(
        "SELECT s.*, c.customer_name, c.phone, c.email, c.address, c.city, c.allergies "
        "FROM sales s LEFT JOIN customers c ON c.customer_id = s.customer_id WHERE s.sale_id = ?", (sale_id,))
    if not sale:
        abort(404)
    items = db.query(
        "SELECT si.*, m.medicine_name, m.generic_name, m.dosage_form, m.batch_no, m.expiry_date, "
        "       si.quantity * si.unit_price AS line_total "
        "FROM sale_items si JOIN medicines m ON m.medicine_id = si.medicine_id "
        "WHERE si.sale_id = ? ORDER BY si.sale_item_id", (sale_id,))
    return render_template("sales/invoice.html", sale=sale, items=items)
