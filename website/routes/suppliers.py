from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db import IntegrityError, get_db
from utils import LIKE_ESCAPE, FormError, clean, csv_response, get_page, like, require

bp = Blueprint("suppliers", __name__, url_prefix="/suppliers")

STATUSES = ("Active", "On Hold")
TERMS = ("COD", "Net 15", "Net 30", "Net 45", "Net 60")
SORTS = {
    "name": "s.supplier_name ASC",
    "spend": "total_spent DESC, s.supplier_name",
    "recent": "last_purchase DESC, s.supplier_name",
    "newest": "s.supplier_id DESC",
}
# Aggregate received purchases per supplier (LEFT JOIN keeps suppliers with no orders)
LIST_SQL = (
    "SELECT s.*, COALESCE(a.orders, 0) AS orders, COALESCE(a.total_spent, 0) AS total_spent, "
    "       a.last_purchase, COALESCE(d.drafts, 0) AS drafts "
    "FROM suppliers s "
    "LEFT JOIN (SELECT supplier_id, COUNT(*) AS orders, SUM(total_amount) AS total_spent, "
    "                  MAX(purchase_date) AS last_purchase "
    "           FROM purchases WHERE status = 'Received' GROUP BY supplier_id) a "
    "       ON a.supplier_id = s.supplier_id "
    "LEFT JOIN (SELECT supplier_id, COUNT(*) AS drafts FROM purchases WHERE status = 'Draft' "
    "           GROUP BY supplier_id) d ON d.supplier_id = s.supplier_id"
)


def _filters():
    where, params = [], []
    q = (request.args.get("q") or "").strip()
    if q:
        pat = like(q)
        where.append("(s.supplier_name LIKE ?" + LIKE_ESCAPE + " OR s.contact_person LIKE ?" + LIKE_ESCAPE +
                     " OR s.phone LIKE ?" + LIKE_ESCAPE + " OR s.email LIKE ?" + LIKE_ESCAPE + ")")
        params += [pat, pat, pat, pat]
    status = request.args.get("status", "")
    if status in STATUSES:
        where.append("s.status = ?")
        params.append(status)
    city = (request.args.get("city") or "").strip()
    if city:
        where.append("s.city = ?")
        params.append(city)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params, {"q": q, "status": status, "city": city, "sort": request.args.get("sort", "name")}


@bp.route("/")
def index():
    db = get_db()
    clause, params, f = _filters()
    total = db.scalar("SELECT COUNT(*) FROM suppliers s" + clause, params, 0)
    page = get_page(total)
    rows = db.query(f"{LIST_SQL}{clause} ORDER BY {SORTS.get(f['sort'], SORTS['name'])} LIMIT ? OFFSET ?",
                    params + [page.per_page, page.offset])
    kpi = db.one(
        "SELECT "
        " (SELECT COUNT(*) FROM suppliers) AS total,"
        " (SELECT COUNT(*) FROM suppliers WHERE status = 'Active') AS active,"
        " (SELECT COUNT(*) FROM suppliers WHERE status = 'On Hold') AS on_hold,"
        " (SELECT COUNT(*) FROM purchases WHERE status = 'Draft') AS drafts,"
        " (SELECT COALESCE(SUM(total_amount), 0) FROM purchases WHERE status = 'Draft') AS draft_value,"
        " (SELECT COALESCE(SUM(total_amount), 0) FROM purchases WHERE status = 'Received') AS spent,"
        " (SELECT COUNT(*) FROM purchases WHERE status = 'Received') AS received")
    cities = [r["city"] for r in db.query(
        "SELECT DISTINCT city FROM suppliers WHERE city IS NOT NULL ORDER BY city")]
    return render_template("suppliers/index.html", rows=rows, page=page, f=f, kpi=kpi, cities=cities,
                           statuses=STATUSES, terms=TERMS)


@bp.route("/export.csv")
def export():
    clause, params, _ = _filters()
    rows = get_db().query(f"{LIST_SQL}{clause} ORDER BY s.supplier_name", params)
    return csv_response(
        "suppliers.csv",
        ["supplier_id", "supplier_name", "contact_person", "phone", "email", "address", "city",
         "payment_terms", "status", "received_orders", "total_spent"],
        [[r["supplier_id"], r["supplier_name"], r["contact_person"], r["phone"], r["email"], r["address"],
          r["city"], r["payment_terms"], r["status"], r["orders"], r["total_spent"]] for r in rows],
    )


def _read(form):
    status = form.get("status") or "Active"
    if status not in STATUSES:
        raise FormError("Invalid supplier status.")
    terms = form.get("payment_terms") or "Net 30"
    if terms not in TERMS:
        raise FormError("Invalid payment terms.")
    return {
        "supplier_name": require(form, "supplier_name", "Supplier name", 150),
        "contact_person": clean(form, "contact_person", 100),
        "phone": require(form, "phone", "Phone", 30),
        "email": clean(form, "email", 120),
        "address": clean(form, "address", 255),
        "city": clean(form, "city", 80),
        "payment_terms": terms,
        "status": status,
    }


def _back():
    return redirect(request.form.get("next") or request.referrer or url_for("suppliers.index"))


@bp.route("/new", methods=["POST"])
def create():
    try:
        data = _read(request.form)
        new_id = get_db().execute(
            f"INSERT INTO suppliers ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})",
            list(data.values())).lastrowid
        flash(f"Supplier '{data['supplier_name']}' added (SUP-{new_id:04d}).", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    return _back()


@bp.route("/<int:supplier_id>/edit", methods=["POST"])
def update(supplier_id):
    db = get_db()
    if not db.one("SELECT supplier_id FROM suppliers WHERE supplier_id = ?", (supplier_id,)):
        abort(404)
    try:
        data = _read(request.form)
        db.execute(f"UPDATE suppliers SET {', '.join(f'{k} = ?' for k in data)} WHERE supplier_id = ?",
                   list(data.values()) + [supplier_id])
        flash(f"Supplier '{data['supplier_name']}' updated.", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    return _back()


@bp.route("/<int:supplier_id>/delete", methods=["POST"])
def delete(supplier_id):
    db = get_db()
    sup = db.one("SELECT supplier_name FROM suppliers WHERE supplier_id = ?", (supplier_id,))
    if not sup:
        abort(404)
    try:
        db.execute("DELETE FROM suppliers WHERE supplier_id = ?", (supplier_id,))
        flash(f"Supplier '{sup['supplier_name']}' deleted.", "success")
    except IntegrityError:
        flash(f"'{sup['supplier_name']}' has purchase records, so it cannot be deleted "
              "(foreign key ON DELETE RESTRICT). Set it to 'On Hold' instead.", "warning")
    return redirect(url_for("suppliers.index"))


@bp.route("/<int:supplier_id>")
def detail(supplier_id):
    db = get_db()
    sup = db.one(LIST_SQL + " WHERE s.supplier_id = ?", (supplier_id,))
    if not sup:
        abort(404)
    purchases = db.query(
        "SELECT p.purchase_id, p.po_number, p.invoice_no, p.purchase_date, p.status, p.total_amount, "
        "       COUNT(pi.purchase_item_id) AS line_count, COALESCE(SUM(pi.quantity), 0) AS units "
        "FROM purchases p LEFT JOIN purchase_items pi ON pi.purchase_id = p.purchase_id "
        "WHERE p.supplier_id = ? "
        "GROUP BY p.purchase_id, p.po_number, p.invoice_no, p.purchase_date, p.status, p.total_amount "
        "ORDER BY p.purchase_date DESC, p.purchase_id DESC", (supplier_id,))
    top_items = db.query(
        "SELECT m.medicine_id, m.medicine_name, SUM(pi.quantity) AS units, "
        "       SUM(pi.quantity * pi.unit_price) AS spent "
        "FROM purchase_items pi JOIN purchases p ON p.purchase_id = pi.purchase_id "
        "JOIN medicines m ON m.medicine_id = pi.medicine_id "
        "WHERE p.supplier_id = ? AND p.status = 'Received' "
        "GROUP BY m.medicine_id, m.medicine_name ORDER BY units DESC LIMIT 5", (supplier_id,))
    return render_template("suppliers/detail.html", sup=sup, purchases=purchases, top_items=top_items,
                           statuses=STATUSES, terms=TERMS)
