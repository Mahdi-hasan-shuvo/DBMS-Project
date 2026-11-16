-- Pharmacy Management System - SQLite schema (mirror of schema_mysql.sql)
-- Same tables, keys, constraints and indexes; only the dialect differs.

PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS sale_items;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS purchase_items;
DROP TABLE IF EXISTS purchases;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS medicines;
DROP TABLE IF EXISTS suppliers;
DROP TABLE IF EXISTS categories;
PRAGMA foreign_keys = ON;

CREATE TABLE categories (
    category_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name  VARCHAR(100) NOT NULL,
    description    VARCHAR(255) NULL,
    CONSTRAINT uq_categories_name UNIQUE (category_name)
);

CREATE TABLE suppliers (
    supplier_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name   VARCHAR(150) NOT NULL,
    contact_person  VARCHAR(100) NULL,
    phone           VARCHAR(30)  NOT NULL,
    email           VARCHAR(120) NULL,
    address         VARCHAR(255) NULL,
    city            VARCHAR(80)  NULL,
    payment_terms   VARCHAR(30)  NOT NULL DEFAULT 'Net 30',
    status          VARCHAR(20)  NOT NULL DEFAULT 'Active',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_suppliers_status CHECK (status IN ('Active', 'On Hold'))
);

CREATE TABLE medicines (
    medicine_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id     INTEGER       NOT NULL,
    medicine_name   VARCHAR(150)  NOT NULL,
    generic_name    VARCHAR(150)  NULL,
    dosage_form     VARCHAR(50)   NULL,
    manufacturer    VARCHAR(120)  NULL,
    sku             VARCHAR(40)   NULL,
    batch_no        VARCHAR(40)   NULL,
    cost_price      DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    price           DECIMAL(10,2) NOT NULL,
    stock_quantity  INTEGER       NOT NULL DEFAULT 0,
    reorder_level   INTEGER       NOT NULL DEFAULT 20,
    expiry_date     DATE          NOT NULL,
    created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_medicines_sku UNIQUE (sku),
    CONSTRAINT fk_medicines_category FOREIGN KEY (category_id)
        REFERENCES categories (category_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_medicines_stock CHECK (stock_quantity >= 0),
    CONSTRAINT chk_medicines_price CHECK (price >= 0 AND cost_price >= 0),
    CONSTRAINT chk_medicines_reorder CHECK (reorder_level >= 0)
);

CREATE TABLE customers (
    customer_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name   VARCHAR(120) NOT NULL,
    gender          VARCHAR(10)  NULL,
    date_of_birth   DATE         NULL,
    phone           VARCHAR(30)  NOT NULL,
    email           VARCHAR(120) NULL,
    address         VARCHAR(255) NULL,
    city            VARCHAR(80)  NULL,
    customer_type   VARCHAR(20)  NOT NULL DEFAULT 'General',
    allergies       VARCHAR(255) NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_customers_type CHECK (customer_type IN ('General', 'Chronic Rx', 'Insured'))
);

CREATE TABLE purchases (
    purchase_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id     INTEGER       NOT NULL,
    po_number       VARCHAR(30)   NULL,
    invoice_no      VARCHAR(50)   NULL,
    purchase_date   DATE          NOT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'Received',
    notes           VARCHAR(255)  NULL,
    subtotal        DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    tax_amount      DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    shipping_cost   DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    total_amount    DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_purchases_po UNIQUE (po_number),
    CONSTRAINT fk_purchases_supplier FOREIGN KEY (supplier_id)
        REFERENCES suppliers (supplier_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_purchases_status CHECK (status IN ('Draft', 'Received'))
);

CREATE TABLE purchase_items (
    purchase_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id      INTEGER       NOT NULL,
    medicine_id      INTEGER       NOT NULL,
    quantity         INTEGER       NOT NULL,
    unit_price       DECIMAL(10,2) NOT NULL,
    CONSTRAINT uq_purchase_items UNIQUE (purchase_id, medicine_id),
    CONSTRAINT fk_purchase_items_purchase FOREIGN KEY (purchase_id)
        REFERENCES purchases (purchase_id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_purchase_items_medicine FOREIGN KEY (medicine_id)
        REFERENCES medicines (medicine_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_purchase_items_qty CHECK (quantity > 0),
    CONSTRAINT chk_purchase_items_price CHECK (unit_price >= 0)
);

CREATE TABLE sales (
    sale_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id      INTEGER       NULL,
    invoice_no       VARCHAR(30)   NULL,
    sale_date        DATETIME      NOT NULL,
    subtotal         DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    discount_amount  DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    tax_amount       DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    total_amount     DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    payment_method   VARCHAR(20)   NOT NULL DEFAULT 'Cash',
    amount_paid      DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    prescription_ref VARCHAR(80)   NULL,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sales_invoice UNIQUE (invoice_no),
    CONSTRAINT fk_sales_customer FOREIGN KEY (customer_id)
        REFERENCES customers (customer_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_sales_payment CHECK (payment_method IN ('Cash', 'Card', 'Mobile Banking', 'Insurance'))
);

CREATE TABLE sale_items (
    sale_item_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id       INTEGER       NOT NULL,
    medicine_id   INTEGER       NOT NULL,
    quantity      INTEGER       NOT NULL,
    unit_price    DECIMAL(10,2) NOT NULL,
    CONSTRAINT uq_sale_items UNIQUE (sale_id, medicine_id),
    CONSTRAINT fk_sale_items_sale FOREIGN KEY (sale_id)
        REFERENCES sales (sale_id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_sale_items_medicine FOREIGN KEY (medicine_id)
        REFERENCES medicines (medicine_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_sale_items_qty CHECK (quantity > 0),
    CONSTRAINT chk_sale_items_price CHECK (unit_price >= 0)
);

CREATE INDEX idx_medicines_name ON medicines (medicine_name);
CREATE INDEX idx_medicines_expiry ON medicines (expiry_date);
CREATE INDEX idx_medicines_category ON medicines (category_id);
CREATE INDEX idx_purchases_supplier ON purchases (supplier_id);
CREATE INDEX idx_purchases_date ON purchases (purchase_date);
CREATE INDEX idx_purchase_items_medicine ON purchase_items (medicine_id);
CREATE INDEX idx_sales_customer ON sales (customer_id);
CREATE INDEX idx_sales_date ON sales (sale_date);
CREATE INDEX idx_sale_items_medicine ON sale_items (medicine_id);
