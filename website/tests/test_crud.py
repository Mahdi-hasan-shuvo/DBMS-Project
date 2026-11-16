"""HTTP-level create / update / delete flows and constraint handling."""
import datetime

FUTURE = (datetime.date.today() + datetime.timedelta(days=400)).isoformat()


def medicine_form(**overrides):
    data = {"medicine_name": "Testamol 250mg", "generic_name": "Testamol", "category_id": "1",
            "dosage_form": "Tablet", "manufacturer": "Test Labs", "sku": "TST-900", "batch_no": "LOT-1",
            "cost_price": "1.50", "price": "3.00", "reorder_level": "10", "expiry_date": FUTURE,
            "stock_quantity": "25"}
    data.update(overrides)
    return data


def flashed(res):
    return res.data.decode()


# ------------------------------------------------------------------ medicines
def test_medicine_create_edit_delete(client, db):
    res = client.post("/medicines/new", data=medicine_form(), follow_redirects=True)
    assert "Testamol 250mg" in flashed(res) and "added" in flashed(res)
    med = db.one("SELECT * FROM medicines WHERE sku = 'TST-900'")
    assert med["stock_quantity"] == 25 and med["price"] == 3.0

    res = client.post(f"/medicines/{med['medicine_id']}/edit",
                      data=medicine_form(price="4.25", stock_quantity="9999"), follow_redirects=True)
    assert "updated" in flashed(res)
    med2 = db.one("SELECT * FROM medicines WHERE medicine_id = ?", (med["medicine_id"],))
    assert med2["price"] == 4.25
    assert med2["stock_quantity"] == 25  # edits never change stock directly

    res = client.post(f"/medicines/{med['medicine_id']}/delete", follow_redirects=True)
    assert "deleted" in flashed(res)
    assert db.one("SELECT 1 AS x FROM medicines WHERE medicine_id = ?", (med["medicine_id"],)) is None


def test_medicine_validation_and_unique_sku(client, db):
    before = db.scalar("SELECT COUNT(*) FROM medicines")
    res = client.post("/medicines/new", data=medicine_form(medicine_name=""), follow_redirects=True)
    assert "Medicine name is required" in flashed(res)
    res = client.post("/medicines/new", data=medicine_form(price="abc"), follow_redirects=True)
    assert "must be a number" in flashed(res)
    res = client.post("/medicines/new", data=medicine_form(price="-1"), follow_redirects=True)
    assert "cannot be less than 0" in flashed(res)
    res = client.post("/medicines/new", data=medicine_form(expiry_date="tomorrow"), follow_redirects=True)
    assert "valid date" in flashed(res)
    existing_sku = db.scalar("SELECT sku FROM medicines WHERE sku IS NOT NULL LIMIT 1")
    res = client.post("/medicines/new", data=medicine_form(sku=existing_sku), follow_redirects=True)
    assert "SKU is already used" in flashed(res)
    res = client.post("/medicines/new", data=medicine_form(category_id="9999", sku="NEW-1"), follow_redirects=True)
    assert "category is invalid" in flashed(res)  # foreign key violation
    assert db.scalar("SELECT COUNT(*) FROM medicines") == before


def test_medicine_with_history_cannot_be_deleted(client, db):
    med_id = db.scalar("SELECT medicine_id FROM sale_items LIMIT 1")
    res = client.post(f"/medicines/{med_id}/delete", follow_redirects=True)
    assert "cannot be deleted" in flashed(res)
    assert db.one("SELECT medicine_id FROM medicines WHERE medicine_id = ?", (med_id,))


def test_medicine_404s(client):
    assert client.post("/medicines/99999/edit", data=medicine_form()).status_code == 404
    assert client.post("/medicines/99999/delete").status_code == 404


# ----------------------------------------------------------------- categories
def test_category_crud_and_restrict(client, db):
    res = client.post("/categories/new", data={"category_name": "Pediatrics", "description": "Kids"},
                      follow_redirects=True)
    assert "added" in flashed(res)
    cid = db.scalar("SELECT category_id FROM categories WHERE category_name = 'Pediatrics'")
    res = client.post("/categories/new", data={"category_name": "Pediatrics"}, follow_redirects=True)
    assert "already exists" in flashed(res)
    client.post(f"/categories/{cid}/edit", data={"category_name": "Paediatrics", "description": ""})
    assert db.scalar("SELECT category_name FROM categories WHERE category_id = ?", (cid,)) == "Paediatrics"
    res = client.post(f"/categories/{cid}/delete", follow_redirects=True)
    assert "deleted" in flashed(res)
    used = db.scalar("SELECT category_id FROM medicines LIMIT 1")
    res = client.post(f"/categories/{used}/delete", follow_redirects=True)
    assert "still has medicines" in flashed(res)


# ------------------------------------------------------------------ suppliers
def test_supplier_crud(client, db):
    form = {"supplier_name": "Acme Meds", "contact_person": "Jo", "phone": "+1 555 0100", "email": "a@b.example",
            "address": "1 Main", "city": "Townsville", "payment_terms": "Net 30", "status": "Active"}
    assert "added" in flashed(client.post("/suppliers/new", data=form, follow_redirects=True))
    sid = db.scalar("SELECT supplier_id FROM suppliers WHERE supplier_name = 'Acme Meds'")
    client.post(f"/suppliers/{sid}/edit", data={**form, "status": "On Hold"})
    assert db.scalar("SELECT status FROM suppliers WHERE supplier_id = ?", (sid,)) == "On Hold"
    bad = client.post("/suppliers/new", data={**form, "payment_terms": "Net 999"}, follow_redirects=True)
    assert "Invalid payment terms" in flashed(bad)
    missing = client.post("/suppliers/new", data={**form, "phone": ""}, follow_redirects=True)
    assert "Phone is required" in flashed(missing)
    assert "deleted" in flashed(client.post(f"/suppliers/{sid}/delete", follow_redirects=True))


def test_supplier_with_purchases_is_protected(client, db):
    sid = db.scalar("SELECT supplier_id FROM purchases LIMIT 1")
    res = client.post(f"/suppliers/{sid}/delete", follow_redirects=True)
    assert "cannot be deleted" in flashed(res)


# ------------------------------------------------------------------ customers
def test_customer_crud_and_quick_add(client, db):
    form = {"customer_name": "Test Patient", "phone": "+1 555 0111", "gender": "Female",
            "date_of_birth": "1990-05-01", "customer_type": "Insured", "allergies": "Penicillin"}
    assert "added" in flashed(client.post("/customers/new", data=form, follow_redirects=True))
    cid = db.scalar("SELECT customer_id FROM customers WHERE customer_name = 'Test Patient'")
    client.post(f"/customers/{cid}/edit", data={**form, "customer_type": "Chronic Rx"})
    assert db.scalar("SELECT customer_type FROM customers WHERE customer_id = ?", (cid,)) == "Chronic Rx"
    assert "Invalid customer type" in flashed(
        client.post("/customers/new", data={**form, "customer_type": "VIP"}, follow_redirects=True))
    assert "deleted" in flashed(client.post(f"/customers/{cid}/delete", follow_redirects=True))

    res = client.post("/customers/quick", data={"customer_name": "Quick One", "phone": "123"})
    assert res.status_code == 200 and res.json["ok"] and res.json["customer"]["customer_name"] == "Quick One"
    res = client.post("/customers/quick", data={"customer_name": "", "phone": "123"})
    assert res.status_code == 400 and not res.json["ok"]


def test_customer_with_sales_is_protected(client, db):
    cid = db.scalar("SELECT customer_id FROM sales WHERE customer_id IS NOT NULL LIMIT 1")
    res = client.post(f"/customers/{cid}/delete", follow_redirects=True)
    assert "sales history" in flashed(res)


# ---------------------------------------------------------------------- sales
def _sellable(db):
    today = datetime.date.today().isoformat()
    return db.one("SELECT medicine_id, stock_quantity FROM medicines WHERE stock_quantity > 5 AND expiry_date >= ? "
                  "ORDER BY medicine_id LIMIT 1", (today,))


def test_pos_checkout_json(client, db):
    med = _sellable(db)
    res = client.post("/sales/checkout", json={"items": [{"medicine_id": med["medicine_id"], "quantity": 2}],
                                               "payment_method": "Card", "customer_id": 1,
                                               "prescription_ref": "RX-TEST"})
    assert res.status_code == 200 and res.json["ok"]
    sale_id = res.json["sale_id"]
    assert db.scalar("SELECT stock_quantity FROM medicines WHERE medicine_id = ?",
                     (med["medicine_id"],)) == med["stock_quantity"] - 2
    invoice = client.get(res.json["redirect"])
    assert invoice.status_code == 200 and b"RX-TEST" in invoice.data
    assert db.scalar("SELECT payment_method FROM sales WHERE sale_id = ?", (sale_id,)) == "Card"


def test_pos_checkout_errors(client, db):
    med = _sellable(db)
    res = client.post("/sales/checkout", json={"items": [{"medicine_id": med["medicine_id"],
                                                          "quantity": med["stock_quantity"] + 1}]})
    assert res.status_code == 400 and "Not enough stock" in res.json["error"]
    res = client.post("/sales/checkout", data="not json", content_type="text/plain")
    assert res.status_code == 400 and "at least one" in res.json["error"]


def test_quick_dispense_form(client, db):
    med = _sellable(db)
    res = client.post("/sales/quick", data={"medicine_id": med["medicine_id"], "quantity": "1",
                                            "payment_method": "Cash"}, follow_redirects=True)
    assert b"Tax Invoice" in res.data
    res = client.post("/sales/quick", data={"medicine_id": med["medicine_id"], "quantity": "100000"},
                      follow_redirects=True)
    assert b"Not enough stock" in res.data


# ------------------------------------------------------------------ purchases
def test_purchase_form_receive_and_draft(client, db):
    med = db.one("SELECT medicine_id, stock_quantity FROM medicines ORDER BY medicine_id LIMIT 1")
    form = {"supplier_id": "1", "invoice_no": "SUP-1", "purchase_date": datetime.date.today().isoformat(),
            "shipping_cost": "0", "notes": "test", "medicine_id": [str(med["medicine_id"]), ""],
            "quantity": ["10", ""], "unit_price": ["2.00", ""], "action": "receive"}
    res = client.post("/purchases/new", data=form, follow_redirects=True)
    assert b"stock updated" in res.data
    assert db.scalar("SELECT stock_quantity FROM medicines WHERE medicine_id = ?",
                     (med["medicine_id"],)) == med["stock_quantity"] + 10

    res = client.post("/purchases/new", data={**form, "action": "draft"}, follow_redirects=True)
    assert b"saved as draft" in res.data
    draft_id = db.scalar("SELECT MAX(purchase_id) FROM purchases")
    assert db.scalar("SELECT status FROM purchases WHERE purchase_id = ?", (draft_id,)) == "Draft"
    client.post(f"/purchases/{draft_id}/receive")
    assert db.scalar("SELECT stock_quantity FROM medicines WHERE medicine_id = ?",
                     (med["medicine_id"],)) == med["stock_quantity"] + 20


def test_purchase_form_errors_rerender(client):
    res = client.post("/purchases/new", data={"supplier_id": "", "medicine_id": ["1"], "quantity": ["1"],
                                              "unit_price": ["1"]})
    assert res.status_code == 400 and b"supplier" in res.data
    res = client.post("/purchases/new", data={"supplier_id": "1"})
    assert res.status_code == 400 and b"at least one medicine" in res.data


def test_delete_draft_via_http(client, db):
    draft = db.scalar("SELECT purchase_id FROM purchases WHERE status = 'Draft' LIMIT 1")
    res = client.post(f"/purchases/{draft}/delete", follow_redirects=True)
    assert b"Draft purchase deleted" in res.data
    received = db.scalar("SELECT purchase_id FROM purchases WHERE status = 'Received' LIMIT 1")
    res = client.post(f"/purchases/{received}/delete", follow_redirects=True)
    assert b"cannot be deleted" in res.data
