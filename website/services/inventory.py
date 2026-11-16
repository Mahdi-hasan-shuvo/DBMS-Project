"""Stock-changing transactions: sales and purchases.

Every function here runs inside one database transaction so the header row,
the line items and the stock adjustment either all commit or all roll back.
Prices for sales are always read from the database, never trusted from the client.
"""
import datetime

PAYMENT_METHODS = ("Cash", "Card", "Mobile Banking", "Insurance")
PURCHASE_STATUSES = ("Draft", "Received")


class InventoryError(Exception):
    """Business-rule failure (bad input, insufficient stock, expired item...)."""


def _money(value):
    return round(float(value) + 1e-9, 2)


def _merge_items(items, with_price=False):
    """Combine duplicate medicine rows and validate ids/quantities."""
    merged = {}
    order = []
    for item in items:
        try:
            med_id = int(item["medicine_id"])
            qty = int(item["quantity"])
        except (KeyError, TypeError, ValueError):
            raise InventoryError("Each item needs a valid medicine and quantity.")
        if qty <= 0:
            raise InventoryError("Quantities must be greater than zero.")
        price = None
        if with_price:
            try:
                price = _money(item["unit_price"])
            except (KeyError, TypeError, ValueError):
                raise InventoryError("Each purchase item needs a valid unit price.")
            if price < 0:
                raise InventoryError("Unit price cannot be negative.")
        if med_id in merged:
            merged[med_id]["quantity"] += qty
            if with_price:
                merged[med_id]["unit_price"] = price
        else:
            merged[med_id] = {"medicine_id": med_id, "quantity": qty, "unit_price": price}
            order.append(med_id)
    if not merged:
        raise InventoryError("Add at least one medicine.")
    return [merged[m] for m in order]


# ------------------------------------------------------------------- sales
def create_sale(db, items, customer_id=None, payment_method="Cash", amount_paid=None,
                discount_percent=0, prescription_ref=None, tax_rate=0.05, sale_date=None):
    """Record a sale, its items and the stock deduction atomically. Returns sale_id."""
    items = _merge_items(items)
    if payment_method not in PAYMENT_METHODS:
        raise InventoryError("Choose a valid payment method.")
    try:
        discount_percent = float(discount_percent or 0)
    except (TypeError, ValueError):
        raise InventoryError("Discount must be a number.")
    if not 0 <= discount_percent <= 100:
        raise InventoryError("Discount must be between 0 and 100 percent.")
    sale_date = sale_date or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = sale_date[:10]

    with db.transaction():
        if customer_id:
            if not db.one("SELECT customer_id FROM customers WHERE customer_id = ?", (customer_id,)):
                raise InventoryError("Selected customer does not exist.")
        else:
            customer_id = None

        lines = []
        for item in items:
            med = db.one(
                "SELECT medicine_id, medicine_name, price, stock_quantity, expiry_date "
                "FROM medicines WHERE medicine_id = ?" + db.for_update(),
                (item["medicine_id"],),
            )
            if not med:
                raise InventoryError(f"Medicine #{item['medicine_id']} does not exist.")
            if med["expiry_date"] < today:
                raise InventoryError(f"{med['medicine_name']} is expired and cannot be sold.")
            if med["stock_quantity"] < item["quantity"]:
                raise InventoryError(
                    f"Not enough stock for {med['medicine_name']}: "
                    f"{med['stock_quantity']} available, {item['quantity']} requested."
                )
            lines.append({**item, "unit_price": _money(med["price"]), "name": med["medicine_name"]})

        subtotal = _money(sum(l["unit_price"] * l["quantity"] for l in lines))
        discount = _money(subtotal * discount_percent / 100)
        tax = _money((subtotal - discount) * tax_rate)
        total = _money(subtotal - discount + tax)
        paid = total if amount_paid in (None, "") else _money(amount_paid)
        if paid < total:
            raise InventoryError(f"Amount paid ({paid:.2f}) is less than the total ({total:.2f}).")

        sale_id = db.execute(
            "INSERT INTO sales (customer_id, sale_date, subtotal, discount_amount, tax_amount, "
            "total_amount, payment_method, amount_paid, prescription_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (customer_id, sale_date, subtotal, discount, tax, total, payment_method, paid,
             (prescription_ref or "").strip() or None),
        ).lastrowid
        db.execute("UPDATE sales SET invoice_no = ? WHERE sale_id = ?",
                   (f"INV-{sale_date[:4]}-{sale_id:05d}", sale_id))

        for line in lines:
            db.execute(
                "INSERT INTO sale_items (sale_id, medicine_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                (sale_id, line["medicine_id"], line["quantity"], line["unit_price"]),
            )
            # Conditional update guards against a concurrent sale emptying the stock.
            res = db.execute(
                "UPDATE medicines SET stock_quantity = stock_quantity - ? "
                "WHERE medicine_id = ? AND stock_quantity >= ?",
                (line["quantity"], line["medicine_id"], line["quantity"]),
            )
            if res.rowcount != 1:
                raise InventoryError(f"Stock for {line['name']} changed; please try again.")
    return sale_id


# --------------------------------------------------------------- purchases
def _apply_purchase_stock(db, purchase_id):
    rows = db.query("SELECT medicine_id, quantity, unit_price FROM purchase_items WHERE purchase_id = ?",
                    (purchase_id,))
    for row in rows:
        db.execute(
            "UPDATE medicines SET stock_quantity = stock_quantity + ?, cost_price = ? WHERE medicine_id = ?",
            (row["quantity"], row["unit_price"], row["medicine_id"]),
        )


def create_purchase(db, supplier_id, items, purchase_date=None, invoice_no=None, notes=None,
                    status="Received", tax_rate=0.05, shipping_cost=0):
    """Record a purchase order. 'Received' adds stock now; 'Draft' leaves stock unchanged."""
    items = _merge_items(items, with_price=True)
    if status not in PURCHASE_STATUSES:
        raise InventoryError("Invalid purchase status.")
    try:
        shipping = _money(shipping_cost or 0)
    except (TypeError, ValueError):
        raise InventoryError("Shipping cost must be a number.")
    if shipping < 0:
        raise InventoryError("Shipping cost cannot be negative.")
    purchase_date = purchase_date or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(purchase_date)
    except ValueError:
        raise InventoryError("Purchase date must be a valid date (YYYY-MM-DD).")

    with db.transaction():
        if not db.one("SELECT supplier_id FROM suppliers WHERE supplier_id = ?", (supplier_id,)):
            raise InventoryError("Selected supplier does not exist.")
        for item in items:
            if not db.one("SELECT medicine_id FROM medicines WHERE medicine_id = ?", (item["medicine_id"],)):
                raise InventoryError(f"Medicine #{item['medicine_id']} does not exist.")

        subtotal = _money(sum(i["unit_price"] * i["quantity"] for i in items))
        tax = _money(subtotal * tax_rate)
        total = _money(subtotal + tax + shipping)
        purchase_id = db.execute(
            "INSERT INTO purchases (supplier_id, invoice_no, purchase_date, status, notes, "
            "subtotal, tax_amount, shipping_cost, total_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (supplier_id, (invoice_no or "").strip() or None, purchase_date, status,
             (notes or "").strip() or None, subtotal, tax, shipping, total),
        ).lastrowid
        db.execute("UPDATE purchases SET po_number = ? WHERE purchase_id = ?",
                   (f"PO-{purchase_date[:4]}-{purchase_id:04d}", purchase_id))
        for item in items:
            db.execute(
                "INSERT INTO purchase_items (purchase_id, medicine_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                (purchase_id, item["medicine_id"], item["quantity"], item["unit_price"]),
            )
        if status == "Received":
            _apply_purchase_stock(db, purchase_id)
    return purchase_id


def receive_purchase(db, purchase_id):
    """Turn a draft purchase into a received one and add its quantities to stock."""
    with db.transaction():
        purchase = db.one("SELECT purchase_id, status FROM purchases WHERE purchase_id = ?" + db.for_update(),
                          (purchase_id,))
        if not purchase:
            raise InventoryError("Purchase not found.")
        if purchase["status"] != "Draft":
            raise InventoryError("Only draft purchases can be received.")
        db.execute("UPDATE purchases SET status = 'Received' WHERE purchase_id = ?", (purchase_id,))
        _apply_purchase_stock(db, purchase_id)


def delete_draft_purchase(db, purchase_id):
    """Delete a draft purchase (its items go with it via ON DELETE CASCADE)."""
    with db.transaction():
        purchase = db.one("SELECT status FROM purchases WHERE purchase_id = ?", (purchase_id,))
        if not purchase:
            raise InventoryError("Purchase not found.")
        if purchase["status"] != "Draft":
            raise InventoryError("Received purchases already changed stock and cannot be deleted.")
        db.execute("DELETE FROM purchases WHERE purchase_id = ?", (purchase_id,))
