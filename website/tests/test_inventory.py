"""Transaction rules: stock moves only through purchases and sales, atomically."""
import datetime

import pytest

from services.inventory import (InventoryError, create_purchase, create_sale, delete_draft_purchase,
                                receive_purchase)


def stock(db, med_id):
    return db.scalar("SELECT stock_quantity FROM medicines WHERE medicine_id = ?", (med_id,))


def sellable(db, minimum=10, skip=()):
    today = datetime.date.today().isoformat()
    rows = db.query("SELECT medicine_id, price, stock_quantity FROM medicines "
                    "WHERE stock_quantity >= ? AND expiry_date >= ? ORDER BY medicine_id", (minimum, today))
    return [r for r in rows if r["medicine_id"] not in skip]


def counts(db):
    return (db.scalar("SELECT COUNT(*) FROM sales"), db.scalar("SELECT COUNT(*) FROM sale_items"))


def test_sale_deducts_stock_and_computes_totals(db):
    a, b = sellable(db)[:2]
    sale_id = create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 3},
                               {"medicine_id": b["medicine_id"], "quantity": 2}],
                          discount_percent=10, tax_rate=0.05)
    assert stock(db, a["medicine_id"]) == a["stock_quantity"] - 3
    assert stock(db, b["medicine_id"]) == b["stock_quantity"] - 2
    sale = db.one("SELECT * FROM sales WHERE sale_id = ?", (sale_id,))
    subtotal = round(a["price"] * 3 + b["price"] * 2, 2)
    discount = round(subtotal * 0.10, 2)
    tax = round((subtotal - discount) * 0.05, 2)
    assert sale["subtotal"] == pytest.approx(subtotal)
    assert sale["discount_amount"] == pytest.approx(discount)
    assert sale["tax_amount"] == pytest.approx(tax)
    assert sale["total_amount"] == pytest.approx(round(subtotal - discount + tax, 2))
    assert sale["invoice_no"] == f"INV-{datetime.date.today().year}-{sale_id:05d}"
    items = db.scalar("SELECT SUM(quantity * unit_price) FROM sale_items WHERE sale_id = ?", (sale_id,))
    assert items == pytest.approx(subtotal)


def test_insufficient_stock_rolls_back_everything(db):
    a, b = sellable(db)[:2]
    before = counts(db)
    with pytest.raises(InventoryError, match="Not enough stock"):
        create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 1},
                         {"medicine_id": b["medicine_id"], "quantity": b["stock_quantity"] + 1}])
    assert counts(db) == before
    assert stock(db, a["medicine_id"]) == a["stock_quantity"]
    assert stock(db, b["medicine_id"]) == b["stock_quantity"]


def test_expired_medicine_cannot_be_sold(db):
    today = datetime.date.today().isoformat()
    expired = db.one("SELECT medicine_id, stock_quantity FROM medicines WHERE expiry_date < ? AND stock_quantity > 0",
                     (today,))
    assert expired, "seed data should contain an expired medicine with stock"
    with pytest.raises(InventoryError, match="expired"):
        create_sale(db, [{"medicine_id": expired["medicine_id"], "quantity": 1}])
    assert stock(db, expired["medicine_id"]) == expired["stock_quantity"]


def test_duplicate_lines_are_merged(db):
    a = sellable(db)[0]
    sale_id = create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 2},
                               {"medicine_id": a["medicine_id"], "quantity": 3}])
    rows = db.query("SELECT quantity FROM sale_items WHERE sale_id = ?", (sale_id,))
    assert [r["quantity"] for r in rows] == [5]
    assert stock(db, a["medicine_id"]) == a["stock_quantity"] - 5


@pytest.mark.parametrize("items,error", [
    ([], "at least one"),
    ([{"medicine_id": 1, "quantity": 0}], "greater than zero"),
    ([{"medicine_id": 1, "quantity": -2}], "greater than zero"),
    ([{"medicine_id": "x", "quantity": 1}], "valid medicine"),
    ([{"medicine_id": 999999, "quantity": 1}], "does not exist"),
])
def test_sale_input_validation(db, items, error):
    with pytest.raises(InventoryError, match=error):
        create_sale(db, items)


def test_underpayment_and_bad_payment_method(db):
    a = sellable(db)[0]
    with pytest.raises(InventoryError, match="less than the total"):
        create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 1}], amount_paid=0.01)
    with pytest.raises(InventoryError, match="payment method"):
        create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 1}], payment_method="Bitcoin")
    with pytest.raises(InventoryError, match="Discount"):
        create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 1}], discount_percent=150)
    with pytest.raises(InventoryError, match="customer"):
        create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 1}], customer_id=999999)
    assert stock(db, a["medicine_id"]) == a["stock_quantity"]


def test_sale_can_empty_stock_exactly(db):
    a = sellable(db)[0]
    create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": a["stock_quantity"]}])
    assert stock(db, a["medicine_id"]) == 0
    with pytest.raises(InventoryError):
        create_sale(db, [{"medicine_id": a["medicine_id"], "quantity": 1}])


def test_received_purchase_adds_stock_and_updates_cost(db):
    med = db.one("SELECT medicine_id, stock_quantity FROM medicines ORDER BY medicine_id LIMIT 1")
    pid = create_purchase(db, 1, [{"medicine_id": med["medicine_id"], "quantity": 40, "unit_price": 7.25}],
                          shipping_cost=10, tax_rate=0.05)
    assert stock(db, med["medicine_id"]) == med["stock_quantity"] + 40
    assert db.scalar("SELECT cost_price FROM medicines WHERE medicine_id = ?", (med["medicine_id"],)) == 7.25
    p = db.one("SELECT * FROM purchases WHERE purchase_id = ?", (pid,))
    assert p["status"] == "Received"
    assert p["subtotal"] == pytest.approx(290.0)
    assert p["tax_amount"] == pytest.approx(14.5)
    assert p["total_amount"] == pytest.approx(314.5)
    assert p["po_number"].startswith("PO-")


def test_draft_purchase_changes_stock_only_when_received(db):
    med = db.one("SELECT medicine_id, stock_quantity FROM medicines ORDER BY medicine_id LIMIT 1")
    pid = create_purchase(db, 1, [{"medicine_id": med["medicine_id"], "quantity": 25, "unit_price": 3}],
                          status="Draft")
    assert stock(db, med["medicine_id"]) == med["stock_quantity"]
    receive_purchase(db, pid)
    assert stock(db, med["medicine_id"]) == med["stock_quantity"] + 25
    with pytest.raises(InventoryError, match="Only draft"):
        receive_purchase(db, pid)  # cannot double-receive
    assert stock(db, med["medicine_id"]) == med["stock_quantity"] + 25


def test_delete_draft_cascades_items_but_received_is_protected(db):
    pid = create_purchase(db, 1, [{"medicine_id": 1, "quantity": 5, "unit_price": 1},
                                  {"medicine_id": 2, "quantity": 5, "unit_price": 1}], status="Draft")
    delete_draft_purchase(db, pid)
    assert db.scalar("SELECT COUNT(*) FROM purchase_items WHERE purchase_id = ?", (pid,)) == 0  # ON DELETE CASCADE
    received = db.scalar("SELECT purchase_id FROM purchases WHERE status = 'Received' LIMIT 1")
    with pytest.raises(InventoryError, match="cannot be deleted"):
        delete_draft_purchase(db, received)


@pytest.mark.parametrize("kwargs,error", [
    ({"supplier_id": 99999}, "supplier"),
    ({"status": "Lost"}, "status"),
    ({"purchase_date": "31-12-2026"}, "valid date"),
    ({"shipping_cost": -5}, "negative"),
])
def test_purchase_validation(db, kwargs, error):
    args = {"supplier_id": 1, "items": [{"medicine_id": 1, "quantity": 1, "unit_price": 1}]}
    args.update(kwargs)
    with pytest.raises(InventoryError, match=error):
        create_purchase(db, **args)


def test_seeded_stock_matches_transaction_history(db):
    """Core invariant: stock = received purchases - sales, for every medicine."""
    rows = db.query(
        "SELECT m.medicine_id, m.stock_quantity, "
        " COALESCE((SELECT SUM(pi.quantity) FROM purchase_items pi JOIN purchases p ON p.purchase_id = pi.purchase_id "
        "           WHERE pi.medicine_id = m.medicine_id AND p.status = 'Received'), 0) "
        " - COALESCE((SELECT SUM(si.quantity) FROM sale_items si WHERE si.medicine_id = m.medicine_id), 0) AS expected "
        "FROM medicines m")
    assert rows and all(r["stock_quantity"] == r["expected"] for r in rows)
    assert db.scalar("SELECT COUNT(*) FROM medicines WHERE stock_quantity < 0") == 0
