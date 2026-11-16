"""Small shared helpers: pagination, form parsing, CSV export, formatting."""
import csv
import datetime
import io
import math

from flask import Response, current_app, request


# ------------------------------------------------------------- pagination
class Page:
    def __init__(self, total, page, per_page):
        self.total = int(total or 0)
        self.per_page = per_page
        self.pages = max(1, math.ceil(self.total / per_page))
        self.page = min(max(1, page), self.pages)
        self.offset = (self.page - 1) * per_page
        self.start = self.offset + 1 if self.total else 0
        self.end = min(self.offset + per_page, self.total)

    def window(self, size=2):
        """Page numbers to show, with None marking a gap."""
        nums = []
        for n in range(1, self.pages + 1):
            if n in (1, self.pages) or abs(n - self.page) <= size:
                nums.append(n)
            elif nums and nums[-1] is not None:
                nums.append(None)
        return nums


def url_with(**changes):
    """Current URL with some query arguments replaced (None removes an argument)."""
    from flask import url_for

    args = request.args.to_dict()
    for key, value in changes.items():
        if value is None or value == "":
            args.pop(key, None)
        else:
            args[key] = value
    return url_for(request.endpoint, **(request.view_args or {}), **args)


def get_page(total, per_page=None):
    per_page = per_page or int_arg("per_page", current_app.config["PER_PAGE"])
    per_page = per_page if per_page in (10, 25, 50, 100) else current_app.config["PER_PAGE"]
    return Page(total, int_arg("page", 1), per_page)


# ----------------------------------------------------------- form parsing
def int_arg(name, default=None, source=None):
    source = source if source is not None else request.args
    try:
        return int(source.get(name, default))
    except (TypeError, ValueError):
        return default


def clean(form, name, max_len=255):
    value = (form.get(name) or "").strip()
    return value[:max_len] if value else None


class FormError(ValueError):
    pass


def require(form, name, label, max_len=255):
    value = clean(form, name, max_len)
    if not value:
        raise FormError(f"{label} is required.")
    return value


def number(form, name, label, kind=float, minimum=0, required=True, default=None):
    raw = (form.get(name) or "").strip()
    if not raw:
        if required:
            raise FormError(f"{label} is required.")
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise FormError(f"{label} must be a number.")
    if minimum is not None and value < minimum:
        raise FormError(f"{label} cannot be less than {minimum}.")
    return round(value, 2) if kind is float else value


def date_value(form, name, label, required=True):
    raw = (form.get(name) or "").strip()
    if not raw:
        if required:
            raise FormError(f"{label} is required.")
        return None
    try:
        return datetime.date.fromisoformat(raw).isoformat()
    except ValueError:
        raise FormError(f"{label} must be a valid date.")


def like(term):
    """Build a LIKE pattern, escaping wildcard characters typed by the user.

    '!' is used as the escape character because a backslash literal is parsed
    differently by MySQL and SQLite. Use together with LIKE_ESCAPE.
    """
    term = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{term}%"


LIKE_ESCAPE = " ESCAPE '!'"


# ------------------------------------------------------------------ export
def csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        "﻿" + buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# -------------------------------------------------------------- formatting
def fmt_money(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0.0
    sign = "-" if value < 0 else ""
    return f"{sign}{current_app.config['CURRENCY']}{abs(value):,.2f}"


def fmt_num(value, decimals=0):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    return f"{value:,.{decimals}f}"


def fmt_date(value, pattern="%b %d, %Y"):
    if not value:
        return ""
    text = str(value)
    try:
        if len(text) > 10:
            return datetime.datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").strftime(pattern)
        return datetime.date.fromisoformat(text).strftime(pattern)
    except ValueError:
        return text


def fmt_datetime(value):
    return fmt_date(value, "%b %d, %Y %I:%M %p")


def days_until(value):
    if not value:
        return None
    try:
        return (datetime.date.fromisoformat(str(value)[:10]) - datetime.date.today()).days
    except ValueError:
        return None


def age_from(dob):
    if not dob:
        return None
    try:
        born = datetime.date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    today = datetime.date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def initials(name):
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


CODE_PREFIX = {"medicine": "MED", "customer": "CUS", "supplier": "SUP", "category": "CAT"}


def code(value, kind):
    try:
        return f"{CODE_PREFIX[kind]}-{int(value):04d}"
    except (TypeError, ValueError):
        return "-"


def stock_status(med, today=None):
    """Classify a medicine row: expired / out / low / expiring / ok."""
    today = today or datetime.date.today().isoformat()
    if med["expiry_date"] < today:
        return "expired"
    if med["stock_quantity"] <= 0:
        return "out"
    if med["stock_quantity"] <= med["reorder_level"]:
        return "low"
    soon = (datetime.date.today() + datetime.timedelta(days=current_app.config["EXPIRY_SOON_DAYS"])).isoformat()
    if med["expiry_date"] <= soon:
        return "expiring"
    return "ok"


def date_range_args(default_days=30):
    """Read ?start=&end= (YYYY-MM-DD), falling back to the last `default_days` days."""
    today = datetime.date.today()
    end = _parse_date(request.args.get("end")) or today
    start = _parse_date(request.args.get("start")) or (end - datetime.timedelta(days=default_days - 1))
    if start > end:
        start, end = end, start
    return start, end


def _parse_date(raw):
    try:
        return datetime.date.fromisoformat(raw) if raw else None
    except ValueError:
        return None
