import pytest

PAGES = [
    ("/", b"Pharmacy Operations Dashboard"),
    ("/medicines/", b"Medicine &amp; Drug Inventory"),
    ("/medicines/?q=amox&category=1&stock=low&expiry=&sort=stock_asc", b"Formulary Records"),
    ("/medicines/?expiry=soon", b"Formulary Records"),
    ("/medicines/?expiry=expired&sort=expiry", b"Formulary Records"),
    ("/medicines/?stock=out", b"Formulary Records"),
    ("/medicines/?page=2&per_page=25", b"Formulary Records"),
    ("/medicines/1", b"Purchase History"),
    ("/categories/", b"Medicine Categories"),
    ("/suppliers/", b"Suppliers Management"),
    ("/suppliers/?status=Active&sort=spend", b"Suppliers Management"),
    ("/suppliers/1", b"Purchase Orders"),
    ("/customers/", b"Customers &amp; Patients Management"),
    ("/customers/?type=Insured&sort=spend&q=a", b"Customers &amp; Patients Management"),
    ("/customers/1", b"Purchase History"),
    ("/purchases/", b"Purchase &amp; Procurement Management"),
    ("/purchases/?status=Draft&period=month", b"Purchase &amp; Procurement Management"),
    ("/purchases/new", b"New Purchase Order Entry"),
    ("/purchases/new?medicine_id=1&supplier_id=1", b"New Purchase Order Entry"),
    ("/purchases/1", b"Purchase Order / Goods Receipt"),
    ("/sales/pos", b"Sales &amp; Billing Terminal (POS)"),
    ("/sales/", b"Sales History &amp; Invoices"),
    ("/sales/?method=Cash&start=2020-01-01&end=2099-01-01&q=INV", b"Sales History &amp; Invoices"),
    ("/sales/1", b"Tax Invoice"),
    ("/alerts/", b"Inventory Alerts &amp; Stock Health Center"),
    ("/alerts/?tab=stock", b"Stock Level Deficits"),
    ("/alerts/?tab=expiry&severity=EXPIRED", b"Expiry Surveillance"),
    ("/alerts/?q=a&category=1", b"Active Alert Formulary Manifest"),
    ("/reports/", b"Dispensary Transaction Audit Ledger"),
    ("/reports/?tab=sales&preset=quarter&group=month", b"Dispensary Transaction Audit Ledger"),
    ("/reports/?tab=sales&preset=custom&start=2026-01-01&end=2025-01-01", b"Reporting period"),
    ("/reports/?tab=sales&preset=today", b"Fast-Moving Pharmaceuticals"),
    ("/reports/?tab=purchases&preset=quarter", b"Supplier Procurement Summary"),
    ("/reports/?tab=inventory", b"Valuation by Category"),
    ("/reports/?tab=stock", b"Low-Stock &amp; Reorder Audit"),
    ("/database/", b"Tables &amp; Relationships"),
    ("/search?q=amox", b"Search results"),
    ("/search?q=INV-", b"Invoices"),
    ("/search", b"Type a search term"),
]


@pytest.mark.parametrize("url,needle", PAGES)
def test_page_renders(client, url, needle):
    res = client.get(url)
    assert res.status_code == 200, url
    assert needle in res.data, url


def test_dashboard_shows_live_counts(client, db):
    res = client.get("/")
    meds = db.scalar("SELECT COUNT(*) FROM medicines")
    assert f">{meds}".encode() in res.data
    assert b"weekChart" in res.data


def test_alerts_show_seeded_shortages(client):
    html = client.get("/alerts/").data
    assert b"Out of stock" in html
    assert b"Expired" in html
    assert b"Zithromax 500mg" in html  # seeded as out of stock


@pytest.mark.parametrize("url,filename", [
    ("/medicines/export.csv", "medicines.csv"),
    ("/suppliers/export.csv", "suppliers.csv"),
    ("/customers/export.csv", "customers.csv"),
    ("/purchases/export.csv", "purchases.csv"),
    ("/sales/export.csv", "sales.csv"),
    ("/alerts/export.csv", "inventory_alerts.csv"),
    ("/reports/export.csv?tab=sales&preset=quarter", "sales_report.csv"),
    ("/reports/export.csv?tab=purchases&preset=quarter", "purchase_report.csv"),
    ("/reports/export.csv?tab=inventory", "inventory_valuation.csv"),
    ("/reports/export.csv?tab=stock", "low_stock_report.csv"),
])
def test_csv_exports(client, url, filename):
    res = client.get(url)
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    assert filename in res.headers["Content-Disposition"]
    lines = res.data.decode("utf-8-sig").strip().splitlines()
    assert len(lines) >= 2  # header + at least one row


def test_backup_dump(client, db):
    res = client.get("/database/backup.sql")
    assert res.status_code == 200
    text = res.data.decode()
    assert "CREATE TABLE medicines" in text
    assert "INSERT INTO sale_items" in text
    assert text.count("INSERT INTO") >= 8
    # parents are restored before children
    assert text.index("INSERT INTO categories") < text.index("INSERT INTO medicines") < text.index("INSERT INTO sale_items")


def test_database_page_integrity_passes(client):
    assert b"Passed" in client.get("/database/").data


@pytest.mark.parametrize("url", ["/medicines/99999", "/suppliers/99999", "/customers/99999", "/purchases/99999",
                                 "/sales/99999", "/no-such-page"])
def test_not_found(client, url):
    res = client.get(url)
    assert res.status_code == 404
    assert b"Page not found" in res.data


def test_bad_date_filter_is_400(client):
    assert client.get("/sales/?start=not-a-date").status_code == 400


@pytest.mark.parametrize("url", ["/", "/medicines/", "/suppliers/", "/customers/", "/purchases/", "/sales/",
                                 "/sales/pos", "/alerts/", "/reports/", "/reports/?tab=purchases",
                                 "/reports/?tab=inventory", "/reports/?tab=stock", "/database/", "/categories/"])
def test_pages_work_on_empty_database(empty_app, url):
    res = empty_app.test_client().get(url)
    assert res.status_code == 200, url
