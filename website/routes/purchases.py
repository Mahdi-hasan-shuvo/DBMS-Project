import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from db import get_db
from services.inventory import InventoryError, create_purchase, delete_draft_purchase, receive_purchase
from utils import LIKE_ESCAPE, csv_response, get_page, int_arg, like

bp = Blueprint("purchases", __name__, url_prefix="/purchases")

LIST_SQL = (
    "SELECT p.*, s.supplier_name, "
    "       (SELECT COUNT(*) FROM purchase_items pi WHERE pi.purchase_id = p.purchase_id) AS line_count, "
    "       (SELECT COALESCE(SUM(pi.quantity), 0) FROM purchase_items pi "
    "         WHERE pi.purchase_id = p.purchase_id) AS units "
    "FROM purchases p JOIN suppliers s ON s.supplier_id = p.supplier_id"
)


def _filters():
    where, params = [], []
    q = (request.args.get("q") or "").strip()
    if q:
        pat = like(q)
        where.append("(p.po_number LIKE ?" + LIKE_ESCAPE + " OR p.invoice_no LIKE ?" + LIKE_ESCAPE +
                     " OR s.supplier_name LIKE ?" + LIKE_ESCAPE + ")")
        params += [pat, pat, pat]
    status = request.args.get("status", "")
    if status in ("Draft", "Received"):
        where.append("p.status = ?")
        params.append(status)
    supplier = int_arg("supplier")
    if supplier:
        where.append("p.supplier_id = ?")
        params.append(supplier)
    period = request.args.get("period", "")
    today = datetime.date.today()
    if period == "month":
        where.append("p.purchase_date >= ?")
        params.append(today.replace(day=1).isoformat())
    elif period == "30":
        where.append("p.purchase_date >= ?")
        params.append((today - datetime.timedelta(days=29)).isoformat())
    elif period == "year":
        where.append("p.purchase_date >= ?")
        params.append(today.replace(month=1, day=1).isoformat())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params, {"q": q, "status": status, "supplier": supplier, "period": period}


@bp.route("/")
def index():
    db = get_db()
    clause, params, f = _filters()
    total = db.scalar("SELECT COUNT(*) FROM purchases p JOIN suppliers s ON s.supplier_id = p.supplier_id"
                      + clause, params, 0)
    page = get_page(total)
    rows = db.query(f"{LIST_SQL}{clause} ORDER BY p.purchase_date DESC, p.purchase_id DESC LIMIT ? OFFSET ?",
                    params + [page.per_page, page.offset])
    year_start = datetime.date.today().replace(month=1, day=1).isoformat()
    kpi = db.one(
        "SELECT "
        " (SELECT COALESCE(SUM(total_amount), 0) FROM purchases WHERE status = 'Received' AND purchase_date >= ?) AS ytd,"
        " (SELECT COUNT(*) FROM purchases WHERE status = 'Received' AND purchase_date >= ?) AS ytd_count,"
        " (SELECT COUNT(*) FROM purchases WHERE status = 'Received') AS received,"
        " (SELECT COALESCE(SUM(pi.quantity), 0) FROM purchase_items pi JOIN purchases p "
        "    ON p.purchase_id = pi.purchase_id WHERE p.status = 'Received') AS units_in,"
        " (SELECT COUNT(*) FROM purchases WHERE status = 'Draft') AS drafts,"
        " (SELECT COALESCE(SUM(total_amount), 0) FROM purchases WHERE status = 'Draft') AS draft_value,"
        " (SELECT COUNT(*) FROM purchases) AS total",
        (year_start, year_start))
    suppliers = db.query("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    return render_template("purchases/index.html", rows=rows, page=page, f=f, kpi=kpi, suppliers=suppliers)


@bp.route("/export.csv")
def export():
    clause, params, _ = _filters()
    rows = get_db().query(f"{LIST_SQL}{clause} ORDER BY p.purchase_date DESC, p.purchase_id DESC", params)
    return csv_response(
        "purchases.csv",
        ["purchase_id", "po_number", "supplier", "invoice_no", "purchase_date", "status", "lines", "units",
         "subtotal", "tax_amount", "shipping_cost", "total_amount"],
        [[r["purchase_id"], r["po_number"], r["supplier_name"], r["invoice_no"], r["purchase_date"],
          r["status"], r["line_count"], r["units"], r["subtotal"], r["tax_amount"], r["shipping_cost"],
          r["total_amount"]] for r in rows],
    )


def _form_context(db, values=None, items=None):
    suppliers = db.query("SELECT supplier_id, supplier_name, status FROM suppliers ORDER BY supplier_name")
    medicines = db.query(
        "SELECT m.medicine_id, m.medicine_name, m.generic_name, m.sku, m.stock_quantity, m.reorder_level, "
        "       m.cost_price FROM medicines m ORDER BY m.medicine_name")
    return {"suppliers": suppliers, "medicines": medicines, "values": values or {}, "items": items or []}


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    if request.method == "GET":
        items = []
        med_id = int_arg("medicine_id")
        if med_id:
            med = db.one("SELECT medicine_id, reorder_level, stock_quantity, cost_price FROM medicines "
                         "WHERE medicine_id = ?", (med_id,))
            if med:
                qty = max(med["reorder_level"] * 3 - med["stock_quantity"], med["reorder_level"], 1)
                items.append({"medicine_id": med["medicine_id"], "quantity": qty, "unit_price": med["cost_price"]})
        values = {"supplier_id": int_arg("supplier_id"), "purchase_date": datetime.date.today().isoformat(),
                  "shipping_cost": "0"}
        return render_template("purchases/new.html", **_form_context(db, values, items))

    form = request.form
    items = [
        {"medicine_id": m, "quantity": q, "unit_price": p}
        for m, q, p in zip(form.getlist("medicine_id"), form.getlist("quantity"), form.getlist("unit_price"))
        if (m or "").strip()
    ]
    status = "Draft" if form.get("action") == "draft" else "Received"
    try:
        supplier_id = int(form.get("supplier_id") or 0)
        purchase_id = create_purchase(
            db, supplier_id, items, purchase_date=form.get("purchase_date") or None,
            invoice_no=form.get("invoice_no"), notes=form.get("notes"), status=status,
            tax_rate=current_app.config["TAX_RATE"], shipping_cost=form.get("shipping_cost") or 0)
    except (InventoryError, ValueError) as exc:
        message = str(exc) if isinstance(exc, InventoryError) else "Select a supplier."
        flash(message, "danger")
        return render_template("purchases/new.html", **_form_context(db, form.to_dict(), items)), 400
    if status == "Draft":
        flash("Purchase saved as draft. Stock will update when you mark it received.", "info")
    else:
        flash("Purchase recorded and stock updated in one transaction.", "success")
    return redirect(url_for("purchases.detail", purchase_id=purchase_id))


@bp.route("/<int:purchase_id>")
def detail(purchase_id):
    db = get_db()
    purchase = db.one(
        "SELECT p.*, s.supplier_name, s.contact_person, s.phone, s.email, s.address, s.city, s.payment_terms "
        "FROM purchases p JOIN suppliers s ON s.supplier_id = p.supplier_id WHERE p.purchase_id = ?",
        (purchase_id,))
    if not purchase:
        abort(404)
    items = db.query(
        "SELECT pi.*, m.medicine_name, m.generic_name, m.sku, m.stock_quantity, "
        "       pi.quantity * pi.unit_price AS line_total "
        "FROM purchase_items pi JOIN medicines m ON m.medicine_id = pi.medicine_id "
        "WHERE pi.purchase_id = ? ORDER BY pi.purchase_item_id", (purchase_id,))
    return render_template("purchases/detail.html", purchase=purchase, items=items)


@bp.route("/<int:purchase_id>/receive", methods=["POST"])
def receive(purchase_id):
    try:
        receive_purchase(get_db(), purchase_id)
        flash("Purchase marked as received; stock quantities increased.", "success")
    except InventoryError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("purchases.detail", purchase_id=purchase_id))


@bp.route("/<int:purchase_id>/delete", methods=["POST"])
def delete(purchase_id):
    try:
        delete_draft_purchase(get_db(), purchase_id)
        flash("Draft purchase deleted.", "success")
        return redirect(url_for("purchases.index"))
    except InventoryError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.detail", purchase_id=purchase_id))
