import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from db import IntegrityError, get_db
from utils import (LIKE_ESCAPE, FormError, clean, csv_response, date_value, get_page, int_arg, like,
                   number, require)

bp = Blueprint("medicines", __name__, url_prefix="/medicines")

SORTS = {
    "name": "m.medicine_name ASC",
    "stock_asc": "m.stock_quantity ASC, m.medicine_name",
    "stock_desc": "m.stock_quantity DESC, m.medicine_name",
    "expiry": "m.expiry_date ASC, m.medicine_name",
    "price_desc": "m.price DESC, m.medicine_name",
    "newest": "m.medicine_id DESC",
}
BASE_SELECT = (
    "SELECT m.*, c.category_name FROM medicines m "
    "JOIN categories c ON c.category_id = m.category_id"
)


def _filters():
    today = datetime.date.today().isoformat()
    soon = (datetime.date.today()
            + datetime.timedelta(days=current_app.config["EXPIRY_SOON_DAYS"])).isoformat()
    where, params = [], []
    q = (request.args.get("q") or "").strip()
    if q:
        pat = like(q)
        where.append("(m.medicine_name LIKE ?" + LIKE_ESCAPE + " OR m.generic_name LIKE ?" + LIKE_ESCAPE +
                     " OR m.sku LIKE ?" + LIKE_ESCAPE + " OR m.manufacturer LIKE ?" + LIKE_ESCAPE + ")")
        params += [pat, pat, pat, pat]
    category = int_arg("category")
    if category:
        where.append("m.category_id = ?")
        params.append(category)
    stock = request.args.get("stock", "")
    if stock == "ok":
        where.append("m.stock_quantity > m.reorder_level")
    elif stock == "low":
        where.append("m.stock_quantity > 0 AND m.stock_quantity <= m.reorder_level")
    elif stock == "out":
        where.append("m.stock_quantity = 0")
    expiry = request.args.get("expiry", "")
    if expiry == "expired":
        where.append("m.expiry_date < ?")
        params.append(today)
    elif expiry == "soon":
        where.append("m.expiry_date >= ? AND m.expiry_date <= ?")
        params += [today, soon]
    elif expiry == "valid":
        where.append("m.expiry_date > ?")
        params.append(soon)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params, {"q": q, "category": category, "stock": stock, "expiry": expiry,
                            "sort": request.args.get("sort", "name")}


@bp.route("/")
def index():
    db = get_db()
    clause, params, f = _filters()
    total = db.scalar("SELECT COUNT(*) FROM medicines m" + clause, params, 0)
    page = get_page(total)
    order = SORTS.get(f["sort"], SORTS["name"])
    rows = db.query(f"{BASE_SELECT}{clause} ORDER BY {order} LIMIT ? OFFSET ?",
                    params + [page.per_page, page.offset])
    today = datetime.date.today()
    soon = (today + datetime.timedelta(days=current_app.config["EXPIRY_SOON_DAYS"])).isoformat()
    kpi = db.one(
        "SELECT COUNT(*) AS total, "
        " SUM(CASE WHEN stock_quantity > reorder_level THEN 1 ELSE 0 END) AS sufficient, "
        " SUM(CASE WHEN stock_quantity <= reorder_level THEN 1 ELSE 0 END) AS low, "
        " SUM(CASE WHEN expiry_date <= ? THEN 1 ELSE 0 END) AS expiring, "
        " COALESCE(SUM(stock_quantity * cost_price), 0) AS stock_value "
        "FROM medicines", (soon,))
    categories = db.query("SELECT category_id, category_name FROM categories ORDER BY category_name")
    return render_template("medicines/index.html", rows=rows, page=page, f=f, kpi=kpi,
                           categories=categories, sorts=SORTS)


@bp.route("/export.csv")
def export():
    db = get_db()
    clause, params, f = _filters()
    rows = db.query(f"{BASE_SELECT}{clause} ORDER BY {SORTS.get(f['sort'], SORTS['name'])}", params)
    return csv_response(
        "medicines.csv",
        ["medicine_id", "medicine_name", "generic_name", "category", "dosage_form", "manufacturer", "sku",
         "batch_no", "cost_price", "price", "stock_quantity", "reorder_level", "expiry_date"],
        [[r["medicine_id"], r["medicine_name"], r["generic_name"], r["category_name"], r["dosage_form"],
          r["manufacturer"], r["sku"], r["batch_no"], r["cost_price"], r["price"], r["stock_quantity"],
          r["reorder_level"], r["expiry_date"]] for r in rows],
    )


def _read_form(form, creating):
    data = {
        "medicine_name": require(form, "medicine_name", "Medicine name", 150),
        "generic_name": clean(form, "generic_name", 150),
        "category_id": number(form, "category_id", "Category", int, 1),
        "dosage_form": clean(form, "dosage_form", 50),
        "manufacturer": clean(form, "manufacturer", 120),
        "sku": clean(form, "sku", 40),
        "batch_no": clean(form, "batch_no", 40),
        "cost_price": number(form, "cost_price", "Cost price", float, 0, required=False, default=0.0),
        "price": number(form, "price", "Selling price"),
        "reorder_level": number(form, "reorder_level", "Reorder level", int, 0, required=False, default=20),
        "expiry_date": date_value(form, "expiry_date", "Expiry date"),
    }
    if creating:
        data["stock_quantity"] = number(form, "stock_quantity", "Opening stock", int, 0,
                                        required=False, default=0)
    return data


def _back():
    return redirect(request.form.get("next") or request.referrer or url_for("medicines.index"))


@bp.route("/new", methods=["POST"])
def create():
    db = get_db()
    try:
        data = _read_form(request.form, creating=True)
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        new_id = db.execute(f"INSERT INTO medicines ({cols}) VALUES ({marks})", list(data.values())).lastrowid
        flash(f"Medicine '{data['medicine_name']}' added (MED-{new_id:04d}).", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    except IntegrityError:
        flash("Could not save: the SKU is already used or the category is invalid.", "danger")
    return _back()


@bp.route("/<int:medicine_id>/edit", methods=["POST"])
def update(medicine_id):
    db = get_db()
    if not db.one("SELECT medicine_id FROM medicines WHERE medicine_id = ?", (medicine_id,)):
        abort(404)
    try:
        data = _read_form(request.form, creating=False)
        sets = ", ".join(f"{k} = ?" for k in data)
        db.execute(f"UPDATE medicines SET {sets} WHERE medicine_id = ?", list(data.values()) + [medicine_id])
        flash(f"Medicine '{data['medicine_name']}' updated.", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    except IntegrityError:
        flash("Could not save: the SKU is already used or the category is invalid.", "danger")
    return _back()


@bp.route("/<int:medicine_id>/delete", methods=["POST"])
def delete(medicine_id):
    db = get_db()
    med = db.one("SELECT medicine_name FROM medicines WHERE medicine_id = ?", (medicine_id,))
    if not med:
        abort(404)
    try:
        db.execute("DELETE FROM medicines WHERE medicine_id = ?", (medicine_id,))
        flash(f"Medicine '{med['medicine_name']}' deleted.", "success")
    except IntegrityError:
        flash(f"'{med['medicine_name']}' has purchase or sales history, so it cannot be deleted "
              "(foreign key ON DELETE RESTRICT).", "warning")
    return redirect(url_for("medicines.index"))


@bp.route("/<int:medicine_id>")
def detail(medicine_id):
    db = get_db()
    med = db.one(BASE_SELECT + " WHERE m.medicine_id = ?", (medicine_id,))
    if not med:
        abort(404)
    purchases = db.query(
        "SELECT p.purchase_id, p.po_number, p.purchase_date, p.status, s.supplier_id, s.supplier_name, "
        "       pi.quantity, pi.unit_price "
        "FROM purchase_items pi "
        "JOIN purchases p ON p.purchase_id = pi.purchase_id "
        "JOIN suppliers s ON s.supplier_id = p.supplier_id "
        "WHERE pi.medicine_id = ? ORDER BY p.purchase_date DESC, p.purchase_id DESC LIMIT 15", (medicine_id,))
    sales = db.query(
        "SELECT sa.sale_id, sa.invoice_no, sa.sale_date, c.customer_id, c.customer_name, "
        "       si.quantity, si.unit_price "
        "FROM sale_items si "
        "JOIN sales sa ON sa.sale_id = si.sale_id "
        "LEFT JOIN customers c ON c.customer_id = sa.customer_id "
        "WHERE si.medicine_id = ? ORDER BY sa.sale_date DESC, sa.sale_id DESC LIMIT 15", (medicine_id,))
    totals = db.one(
        "SELECT "
        " (SELECT COALESCE(SUM(pi.quantity), 0) FROM purchase_items pi JOIN purchases p "
        "    ON p.purchase_id = pi.purchase_id WHERE pi.medicine_id = ? AND p.status = 'Received') AS purchased,"
        " (SELECT COALESCE(SUM(quantity), 0) FROM sale_items WHERE medicine_id = ?) AS sold,"
        " (SELECT COALESCE(SUM(quantity * unit_price), 0) FROM sale_items WHERE medicine_id = ?) AS revenue",
        (medicine_id, medicine_id, medicine_id))
    categories = db.query("SELECT category_id, category_name FROM categories ORDER BY category_name")
    return render_template("medicines/detail.html", med=med, purchases=purchases, sales=sales,
                           totals=totals, categories=categories)
