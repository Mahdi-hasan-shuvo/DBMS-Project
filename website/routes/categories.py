from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db import IntegrityError, get_db
from utils import FormError, clean, require

bp = Blueprint("categories", __name__, url_prefix="/categories")


@bp.route("/")
def index():
    db = get_db()
    rows = db.query(
        "SELECT c.category_id, c.category_name, c.description, "
        "       COUNT(m.medicine_id) AS medicines, "
        "       COALESCE(SUM(m.stock_quantity), 0) AS units, "
        "       COALESCE(SUM(m.stock_quantity * m.cost_price), 0) AS stock_value "
        "FROM categories c LEFT JOIN medicines m ON m.category_id = c.category_id "
        "GROUP BY c.category_id, c.category_name, c.description "
        "ORDER BY c.category_name")
    return render_template("categories/index.html", rows=rows)


def _read(form):
    return require(form, "category_name", "Category name", 100), clean(form, "description", 255)


@bp.route("/new", methods=["POST"])
def create():
    try:
        name, desc = _read(request.form)
        get_db().execute("INSERT INTO categories (category_name, description) VALUES (?, ?)", (name, desc))
        flash(f"Category '{name}' added.", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    except IntegrityError:
        flash("A category with that name already exists.", "danger")
    return redirect(url_for("categories.index"))


@bp.route("/<int:category_id>/edit", methods=["POST"])
def update(category_id):
    db = get_db()
    if not db.one("SELECT category_id FROM categories WHERE category_id = ?", (category_id,)):
        abort(404)
    try:
        name, desc = _read(request.form)
        db.execute("UPDATE categories SET category_name = ?, description = ? WHERE category_id = ?",
                   (name, desc, category_id))
        flash(f"Category '{name}' updated.", "success")
    except FormError as exc:
        flash(str(exc), "danger")
    except IntegrityError:
        flash("A category with that name already exists.", "danger")
    return redirect(url_for("categories.index"))


@bp.route("/<int:category_id>/delete", methods=["POST"])
def delete(category_id):
    db = get_db()
    cat = db.one("SELECT category_name FROM categories WHERE category_id = ?", (category_id,))
    if not cat:
        abort(404)
    try:
        db.execute("DELETE FROM categories WHERE category_id = ?", (category_id,))
        flash(f"Category '{cat['category_name']}' deleted.", "success")
    except IntegrityError:
        flash(f"'{cat['category_name']}' still has medicines, so it cannot be deleted "
              "(foreign key ON DELETE RESTRICT).", "warning")
    return redirect(url_for("categories.index"))
