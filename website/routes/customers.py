import datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from db import IntegrityError, get_db
from utils import LIKE_ESCAPE, FormError, clean, csv_response, date_value, get_page, like, require

bp = Blueprint("customers", __name__, url_prefix="/customers")

TYPES = ("General", "Chronic Rx", "Insured")
GENDERS = ("Male", "Female", "Other")
SORTS = {
    "recent": "last_visit DESC, c.customer_name",
    "name": "c.customer_name ASC",
    "spend": "total_spent DESC, c.customer_name",
    "visits": "visits DESC, c.customer_name",
    "newest": "c.customer_id DESC",
}
LIST_SQL = (
    "SELECT c.*, COALESCE(a.visits, 0) AS visits, COALESCE(a.total_spent, 0) AS total_spent, a.last_visit "
    "FROM customers c "
    "LEFT JOIN (SELECT customer_id, COUNT(*) AS visits, SUM(total_amount) AS total_spent, "
    "                  MAX(sale_date) AS last_visit "
    "           FROM sales WHERE customer_id IS NOT NULL GROUP BY customer_id) a "
    "       ON a.customer_id = c.customer_id"
)


def _filters():
    where, params = [], []
    q = (request.args.get("q") or "").strip()
    if q:
        pat = like(q)
        where.append("(c.customer_name LIKE ?" + LIKE_ESCAPE + " OR c.phone LIKE ?" + LIKE_ESCAPE +
                     " OR c.email LIKE ?" + LIKE_ESCAPE + " OR c.city LIKE ?" + LIKE_ESCAPE + ")")
        params += [pat, pat, pat, pat]
    ctype = request.args.get("type", "")
    if ctype in TYPES:
        where.append("c.customer_type = ?")
        params.append(ctype)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params, {"q": q, "type": ctype, "sort": request.args.get("sort", "recent")}


@bp.route("/")
def index():
    db = get_db()
    clause, params, f = _filters()
    total = db.scalar("SELECT COUNT(*) FROM customers c" + clause, params, 0)
    page = get_page(total)
    rows = db.query(f"{LIST_SQL}{clause} ORDER BY {SORTS.get(f['sort'], SORTS['recent'])} LIMIT ? OFFSET ?",
                    params + [page.per_page, page.offset])
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    kpi = db.one(
        "SELECT "
        " (SELECT COUNT(*) FROM customers) AS total,"
        " (SELECT COUNT(*) FROM customers WHERE created_at >= ?) AS new_week,"
        " (SELECT COUNT(*) FROM customers WHERE customer_type = 'Chronic Rx') AS chronic,"
        " (SELECT COUNT(*) FROM customers WHERE customer_type = 'Insured') AS insured,"
        " (SELECT COUNT(*) FROM customers WHERE allergies IS NOT NULL) AS allergies,"
        " (SELECT COALESCE(SUM(total_amount), 0) FROM sales WHERE customer_id IS NOT NULL) AS volume,"
        " (SELECT COUNT(*) FROM sales WHERE customer_id IS NOT NULL) AS orders",
        (week_ago,))
    return render_template("customers/index.html", rows=rows, page=page, f=f, kpi=kpi, types=TYPES,
                           genders=GENDERS, sorts=SORTS)


@bp.route("/export.csv")
def export():
    clause, params, _ = _filters()
    rows = get_db().query(f"{LIST_SQL}{clause} ORDER BY c.customer_name", params)
    return csv_response(
        "customers.csv",
        ["customer_id", "customer_name", "gender", "date_of_birth", "phone", "email", "address", "city",
         "customer_type", "allergies", "visits", "total_spent"],
        [[r["customer_id"], r["customer_name"], r["gender"], r["date_of_birth"], r["phone"], r["email"],
          r["address"], r["city"], r["customer_type"], r["allergies"], r["visits"], r["total_spent"]]
         for r in rows],
    )


def _read(form):
    ctype = form.get("customer_type") or "General"
    if ctype not in TYPES:
        raise FormError("Invalid customer type.")
    gender = form.get("gender") or None
    if gender and gender not in GENDERS:
        raise FormError("Invalid gender.")
    return {
        "customer_name": require(form, "customer_name", "Customer name", 120),
        "gender": gender,
        "date_of_birth": date_value(form, "date_of_birth", "Date of birth", required=False),
        "phone": require(form, "phone", "Phone", 30),
        "email": clean(form, "email", 120),
        "address": clean(form, "address", 255),
        "city": clean(form, "city", 80),
        "customer_type": ctype,
        "allergies": clean(form, "allergies", 255),
    }


def _insert(data):
    return get_db().execute(
        f"INSERT INTO customers ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})",
        list(data.values())).lastrowid


def _back():
    return redirect(request.form.get("next") or request.referrer or url_for("customers.index"))


@bp.route("/new", methods=["POST"])
def create():
    try:
        data = _read(request.form)
        new_id = _insert(data)
        flash(f"Customer '{data['customer_name']}' added (CUS-{new_id:04d}).", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    return _back()


@bp.route("/quick", methods=["POST"])
def quick_create():
    """JSON endpoint used by the POS 'Add New Patient' dialog."""
    try:
        data = _read(request.form)
    except FormError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    new_id = _insert(data)
    return jsonify(ok=True, customer={"customer_id": new_id, "customer_name": data["customer_name"],
                                      "phone": data["phone"], "allergies": data["allergies"],
                                      "customer_type": data["customer_type"]})


@bp.route("/<int:customer_id>/edit", methods=["POST"])
def update(customer_id):
    db = get_db()
    if not db.one("SELECT customer_id FROM customers WHERE customer_id = ?", (customer_id,)):
        abort(404)
    try:
        data = _read(request.form)
        db.execute(f"UPDATE customers SET {', '.join(f'{k} = ?' for k in data)} WHERE customer_id = ?",
                   list(data.values()) + [customer_id])
        flash(f"Customer '{data['customer_name']}' updated.", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    return _back()


@bp.route("/<int:customer_id>/delete", methods=["POST"])
def delete(customer_id):
    db = get_db()
    cust = db.one("SELECT customer_name FROM customers WHERE customer_id = ?", (customer_id,))
    if not cust:
        abort(404)
    try:
        db.execute("DELETE FROM customers WHERE customer_id = ?", (customer_id,))
        flash(f"Customer '{cust['customer_name']}' deleted.", "success")
    except IntegrityError:
        flash(f"'{cust['customer_name']}' has sales history, so the record is kept "
              "(foreign key ON DELETE RESTRICT).", "warning")
    return redirect(url_for("customers.index"))


@bp.route("/<int:customer_id>")
def detail(customer_id):
    db = get_db()
    cust = db.one(LIST_SQL + " WHERE c.customer_id = ?", (customer_id,))
    if not cust:
        abort(404)
    sales = db.query(
        "SELECT s.sale_id, s.invoice_no, s.sale_date, s.total_amount, s.payment_method, s.prescription_ref, "
        "       COUNT(si.sale_item_id) AS line_count, COALESCE(SUM(si.quantity), 0) AS units "
        "FROM sales s LEFT JOIN sale_items si ON si.sale_id = s.sale_id "
        "WHERE s.customer_id = ? "
        "GROUP BY s.sale_id, s.invoice_no, s.sale_date, s.total_amount, s.payment_method, s.prescription_ref "
        "ORDER BY s.sale_date DESC, s.sale_id DESC", (customer_id,))
    favourites = db.query(
        "SELECT m.medicine_id, m.medicine_name, SUM(si.quantity) AS units "
        "FROM sale_items si JOIN sales s ON s.sale_id = si.sale_id "
        "JOIN medicines m ON m.medicine_id = si.medicine_id "
        "WHERE s.customer_id = ? GROUP BY m.medicine_id, m.medicine_name "
        "ORDER BY units DESC LIMIT 5", (customer_id,))
    return render_template("customers/detail.html", cust=cust, sales=sales, favourites=favourites,
                           types=TYPES, genders=GENDERS)
