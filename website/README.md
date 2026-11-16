# PharmaCare DBMS — Flask website

Pharmacy Management System built with **Python Flask**, **HTML (Jinja templates)**, **Bootstrap 5** (components) and
**Tailwind CSS** (utilities, `tw-` prefix), on **SQLite** (default) or **MySQL / MariaDB (XAMPP)**.
The UI follows the mockups in `../251-115-030_251-115-022/`.

## Run it (Windows)

```powershell
cd website
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Open http://127.0.0.1:5000. On first start the app creates the tables and loads ~4 months of demo data
(47 medicines, 12 suppliers, 36 customers, ~440 sales) into `instance/pharmacy_management.db`.

All CSS/JS libraries are stored in `static/vendor/`, so the site works offline (only the Google font needs internet;
it falls back to system fonts).

## Use MySQL (XAMPP)

1. Start **MySQL** in the XAMPP Control Panel.
2. Copy `.env.example` to `.env` and set `DB_ENGINE=mysql` (user `root`, empty password is the XAMPP default).
3. Run `.venv\Scripts\python app.py`. The app creates the `pharmacy_management` database, tables and demo data.

Alternatively import `database/pharmacy_management.sql` in phpMyAdmin (Import tab). It contains the schema and the
demo data. The demo dates are relative to the day the file was generated, so `flask --app app seed` gives fresher data.

## Commands

| Task | Command |
|---|---|
| Run dev server | `.venv\Scripts\python app.py` |
| Reset to demo data | `.venv\Scripts\flask --app app seed` |
| Empty schema (no data) | `.venv\Scripts\flask --app app init-db` |
| Run all tests | `.venv\Scripts\python -m pytest` |
| Run one test | `.venv\Scripts\python -m pytest tests/test_inventory.py::test_insufficient_stock_rolls_back_everything` |

## Features

- **Dashboard:** today's sales, KPIs, 7-day Rx/OTC revenue chart, quick dispense, recent sales/purchases, low-stock and expiry lists
- **Medicines:** search, filters, sort, pagination, add/edit dialog, CSV export, per-medicine purchase/sales history
- **Categories, Suppliers, Customers:** full CRUD, detail pages, CSV export, allergy records
- **Purchases:** multi-item purchase orders; *Received* adds stock immediately, *Draft* waits until marked received
- **Sales & Billing (POS):** search/scan, category chips, cart, discount, 5% tax, payment methods, change, allergy warning,
  keyboard shortcuts (F2 search, Enter add, F4 customer, F9 pay), printable invoice
- **Inventory Alerts:** low stock, out of stock, expiring (30/90 days) and expired; classification done in SQL with `CASE`
- **Reports:** sales (daily/monthly, COGS, margin, top 5), purchases by supplier, inventory valuation, low stock & expiry, CSV export
- **Database page:** tables, keys, FK rules, ER diagram, stock-integrity check, full `.sql` backup download

## DBMS concepts shown

8 normalized tables with PK/FK, `ON DELETE RESTRICT/CASCADE`, `UNIQUE` and `CHECK` constraints (e.g. stock can't go
negative), indexes, JOINs, LEFT JOINs, GROUP BY aggregates, derived tables, correlated subqueries, prepared statements,
and ACID transactions: each sale/purchase writes its header, its items and the stock change in one transaction
(with `SELECT ... FOR UPDATE` row locks on MySQL).
