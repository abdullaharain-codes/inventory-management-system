-- =============================================
-- Database: inventory_db
-- Complete schema for Inventory Management System
-- =============================================

CREATE DATABASE IF NOT EXISTS inventory_db;
USE inventory_db;

-- =============================================
-- Categories table (Phase 2)
-- =============================================
CREATE TABLE IF NOT EXISTS categories (
    category_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    parent_category_id INT DEFAULT NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_category_parent
        FOREIGN KEY (parent_category_id) REFERENCES categories(category_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- =============================================
-- Users table
-- =============================================
CREATE TABLE users (
    user_id          INT PRIMARY KEY AUTO_INCREMENT,
    name             VARCHAR(100) NOT NULL,
    email            VARCHAR(100) NOT NULL UNIQUE,
    password_hash    VARCHAR(255) NOT NULL,
    role             ENUM('admin','manager','staff') DEFAULT 'staff',
    is_active        TINYINT(1) DEFAULT 1,
    failed_attempts  INT DEFAULT 0,
    locked_until     DATETIME DEFAULT NULL,
    reset_token      VARCHAR(255) DEFAULT NULL,
    reset_token_expiry DATETIME DEFAULT NULL,
    created_at       TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =============================================
-- Suppliers table
-- =============================================
CREATE TABLE suppliers (
    supplier_id             INT PRIMARY KEY AUTO_INCREMENT,
    name                    VARCHAR(100) NOT NULL,
    contact_person          VARCHAR(100),
    phone                   VARCHAR(20),
    email                   VARCHAR(100) UNIQUE,
    address                 TEXT,
    tax_registration_number VARCHAR(50) DEFAULT NULL UNIQUE,
    payment_terms           VARCHAR(100) DEFAULT NULL,
    notes                   TEXT DEFAULT NULL,
    created_at              TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =============================================
-- Products table
-- =============================================
CREATE TABLE products (
    product_id     INT PRIMARY KEY AUTO_INCREMENT,
    name           VARCHAR(100) NOT NULL,
    description    TEXT,
    category       VARCHAR(50),
    category_id    INT DEFAULT NULL,
    sku            VARCHAR(50) DEFAULT NULL UNIQUE,
    barcode        VARCHAR(50) DEFAULT NULL UNIQUE,
    unit_of_measure VARCHAR(20) DEFAULT 'pcs',
    tax_rate       DECIMAL(5,2) DEFAULT 0.00,
    image_path     VARCHAR(255) DEFAULT NULL,
    price          DECIMAL(10,2) NOT NULL,
    cost_price     DECIMAL(10,2) DEFAULT NULL,
    stock_quantity          INT DEFAULT 0,
    minimum_stock_threshold INT DEFAULT 10,
    reorder_quantity        INT DEFAULT 50,
    expiry_date             DATE DEFAULT NULL,
    supplier_id    INT,
    created_at     TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_product_supplier
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        ON DELETE SET NULL,
    CONSTRAINT fk_product_category
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- =============================================
-- Sales table
-- total_amount = quantity_sold * sale_price (generated)
-- =============================================
CREATE TABLE sales (
    sale_id       INT PRIMARY KEY AUTO_INCREMENT,
    product_id    INT NOT NULL,
    product_name  VARCHAR(100) DEFAULT NULL,
    quantity_sold INT NOT NULL,
    sale_price    DECIMAL(10,2) NOT NULL,
    total_amount  DECIMAL(10,2) GENERATED ALWAYS AS (quantity_sold * sale_price) STORED,
    sale_date     DATE NOT NULL,
    notes         TEXT,
    created_at    TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sale_product
        FOREIGN KEY (product_id) REFERENCES products(product_id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- =============================================
-- Bills table
-- discount_amount = subtotal * discount_percent / 100 (generated)
-- grand_total     = subtotal - discount_amount + gst_amount (generated)
-- =============================================
CREATE TABLE bills (
    bill_id          INT PRIMARY KEY AUTO_INCREMENT,
    bill_number      VARCHAR(20) NOT NULL UNIQUE,
    bill_date        DATE NOT NULL,
    discount_percent DECIMAL(5,2) DEFAULT 0,
    gst_percent      DECIMAL(5,2) DEFAULT 0,
    subtotal         DECIMAL(10,2) NOT NULL,
    discount_amount  DECIMAL(10,2) GENERATED ALWAYS AS (ROUND((subtotal * discount_percent / 100), 2)) STORED,
    gst_amount       DECIMAL(10,2) DEFAULT 0,
    grand_total      DECIMAL(10,2) GENERATED ALWAYS AS (ROUND(((subtotal - (subtotal * discount_percent / 100)) + gst_amount), 2)) STORED,
    customer_name    VARCHAR(100),
    customer_phone   VARCHAR(20),
    payment_method   ENUM('cash','card','online','credit') DEFAULT 'cash',
    payment_status   ENUM('paid','pending') DEFAULT 'paid',
    notes            TEXT,
    created_at       TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =============================================
-- Bill items table
-- item_total = quantity * unit_price (generated)
-- =============================================
CREATE TABLE bill_items (
    item_id    INT PRIMARY KEY AUTO_INCREMENT,
    bill_id    INT NOT NULL,
    product_id INT NOT NULL,
    product_name VARCHAR(100) DEFAULT NULL,
    quantity   INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    item_total DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    CONSTRAINT fk_billitem_bill    FOREIGN KEY (bill_id)    REFERENCES bills(bill_id)    ON DELETE CASCADE,
    CONSTRAINT fk_billitem_product FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- =============================================
-- Pending payments table (credit sales tracking)
-- =============================================
CREATE TABLE pending_payments (
    payment_id     INT PRIMARY KEY AUTO_INCREMENT,
    bill_id        INT NOT NULL UNIQUE,
    customer_name  VARCHAR(100) NOT NULL,
    customer_phone VARCHAR(20),
    amount_due     DECIMAL(10,2) NOT NULL,
    amount_paid    DECIMAL(10,2) DEFAULT 0,
    due_date       DATE,
    status         ENUM('pending','partial','paid') DEFAULT 'pending',
    notes          TEXT,
    created_at     TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_pending_bill FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- =============================================
-- Refunds table
-- =============================================
CREATE TABLE refunds (
    refund_id        INT PRIMARY KEY AUTO_INCREMENT,
    bill_id          INT NOT NULL,
    product_id       INT NOT NULL,
    quantity_returned INT NOT NULL,
    refund_amount    DECIMAL(10,2) NOT NULL,
    reason           TEXT,
    refund_date      DATE NOT NULL,
    created_at       TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_refund_bill    FOREIGN KEY (bill_id)    REFERENCES bills(bill_id)    ON DELETE CASCADE,
    CONSTRAINT fk_refund_product FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- =============================================
-- Notifications table (Phase 9)
-- =============================================
CREATE TABLE IF NOT EXISTS notifications (
    notification_id   INT PRIMARY KEY AUTO_INCREMENT,
    user_id           INT DEFAULT NULL,
    target_role       ENUM('admin','manager','staff','all') DEFAULT 'all',
    title             VARCHAR(200) NOT NULL,
    message           TEXT NOT NULL,
    notification_type ENUM('low_stock','expiry_soon','pending_adjustment','new_po','po_approved','po_received','general','out_of_stock','adjustment_approved','adjustment_rejected','staff_login','order_created','pending_payment','payment_received','product_added','product_updated','product_deleted','sale_completed','po_cancelled','supplier_added','supplier_updated','supplier_deleted','user_created','user_updated','user_deleted') NOT NULL,
    is_read           TINYINT DEFAULT 0,
    related_id        INT DEFAULT NULL,
    related_type      VARCHAR(50) DEFAULT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_notification_user
        FOREIGN KEY (user_id) REFERENCES users(user_id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- =============================================
-- Trigger(s)
-- =============================================

-- trg_reduce_stock was removed: sales.py manually deducts stock instead.
-- Only the billing path relies on this DB trigger.
-- Auto-deduct stock on bill item insert
CREATE TRIGGER trg_bill_reduce_stock
    AFTER INSERT ON bill_items
    FOR EACH ROW
    UPDATE products
    SET stock_quantity = stock_quantity - NEW.quantity
    WHERE product_id = NEW.product_id;

-- =============================================
-- Sample data: suppliers
-- =============================================
INSERT INTO suppliers (name, contact_person, phone, email, address, tax_registration_number, payment_terms, notes) VALUES
('Tech Distributors Inc.', 'John Smith', '(555) 123-4567', 'john.smith@techdist.com', '123 Industrial Pkwy, Chicago, IL 60607', 'TRN-101-2024', 'Net 30', 'Preferred electronics distributor'),
('Global Electronics Ltd.', 'Sarah Johnson', '(555) 234-5678', 'sarah.j@globalelec.com', '456 Commerce Blvd, Austin, TX 78701', 'TRN-102-2024', 'Net 60', 'International shipping partner'),
('Office Supply Co.', 'Michael Brown', '(555) 345-6789', 'michael.brown@officesupply.com', '789 Market St, Denver, CO 80202', NULL, 'Cash on Delivery', 'Local supplier — quick delivery'),
('Premium Parts Warehouse', 'Emily Davis', '(555) 456-7890', 'emily.davis@premiumparts.com', '321 Distribution Way, Seattle, WA 98101', 'TRN-104-2024', 'Net 30', 'Premium quality parts specialist'),
('Value Electronics', 'David Wilson', '(555) 567-8901', 'david.wilson@valueelec.com', '654 Logistics Dr, Atlanta, GA 30303', NULL, NULL, NULL);

-- =============================================
-- Sample data: products
-- =============================================
INSERT INTO products (name, description, category, price, stock_quantity, supplier_id) VALUES
('Laptop Pro X15', 'High-performance laptop with 16GB RAM, 512GB SSD', 'Electronics', 1299.99, 50, 1),
('Wireless Mouse M3', 'Ergonomic wireless mouse with dual connectivity', 'Accessories', 29.99, 200, 1),
('Monitor 27" 4K', '27-inch 4K UHD monitor with HDR support', 'Electronics', 449.99, 35, 2),
('Office Desk Chair', 'Ergonomic mesh office chair with lumbar support', 'Furniture', 189.99, 25, 3),
('USB-C Hub 7-in-1', 'Multiport USB-C hub with HDMI, USB, Ethernet', 'Accessories', 59.99, 150, 4);

-- =============================================
-- Sample data: sales
-- (Trigger trg_reduce_stock will auto-deduct stock on each insert)
-- =============================================
INSERT INTO sales (product_id, quantity_sold, sale_price, sale_date, notes) VALUES
(1, 3, 1299.99, '2024-01-15', 'Bulk order for corporate client'),
(2, 25, 29.99, '2024-01-18', 'Office supply restock'),
(3, 5, 449.99, '2024-01-20', 'Graphic design department purchase'),
(1, 2, 1299.99, '2024-01-22', 'Individual customer purchase'),
(5, 15, 59.99, '2024-01-25', 'IT department bulk order');

-- =============================================
-- Activity Logs table
-- =============================================
CREATE TABLE IF NOT EXISTS activity_logs (
    log_id       INT PRIMARY KEY AUTO_INCREMENT,
    user_id      INT NOT NULL,
    user_role    VARCHAR(20) NOT NULL,
    module       VARCHAR(50) NOT NULL,
    action_type  VARCHAR(50) NOT NULL,
    description  TEXT,
    timestamp    TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_module (module),
    INDEX idx_action_type (action_type),
    INDEX idx_user_id (user_id),
    INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB;

-- =============================================
-- Stock Ledger table (Phase 5)
-- =============================================
CREATE TABLE IF NOT EXISTS stock_ledger (
    ledger_id       INT PRIMARY KEY AUTO_INCREMENT,
    product_id      INT DEFAULT NULL,
    product_name    VARCHAR(100) NOT NULL,
    movement_type   ENUM('sale','bill_sale','refund','adjustment','purchase','purchase_receive','opening_balance') NOT NULL,
    quantity_change INT NOT NULL,
    quantity_before INT NOT NULL,
    quantity_after  INT NOT NULL,
    reference_id    INT DEFAULT NULL,
    reference_type  VARCHAR(20) DEFAULT NULL,
    actor_user_id   INT DEFAULT NULL,
    actor_name      VARCHAR(100) DEFAULT NULL,
    notes           TEXT DEFAULT NULL,
    created_at      TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ledger_product_id (product_id),
    INDEX idx_ledger_movement_type (movement_type),
    INDEX idx_ledger_created_at (created_at),
    CONSTRAINT fk_ledger_product
        FOREIGN KEY (product_id) REFERENCES products(product_id)
        ON DELETE SET NULL,
    CONSTRAINT fk_ledger_user
        FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- =============================================
-- Stock Adjustments table (Phase 6)
-- =============================================
CREATE TABLE IF NOT EXISTS stock_adjustments (
    adjustment_id        INT PRIMARY KEY AUTO_INCREMENT,
    product_id           INT DEFAULT NULL,
    product_name         VARCHAR(100) NOT NULL,
    adjustment_type      ENUM('add','remove') NOT NULL,
    quantity             INT NOT NULL,
    reason_code          ENUM('damaged','expired','audit_correction','opening_balance','other') NOT NULL,
    notes                TEXT DEFAULT NULL,
    status               ENUM('pending','approved','rejected') DEFAULT 'pending',
    requested_by_user_id INT DEFAULT NULL,
    requested_by_name    VARCHAR(100) DEFAULT NULL,
    approved_by_user_id  INT DEFAULT NULL,
    approved_by_name     VARCHAR(100) DEFAULT NULL,
    created_at           TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at          TIMESTAMP NULL DEFAULT NULL,
    CONSTRAINT fk_adjustment_product
        FOREIGN KEY (product_id) REFERENCES products(product_id)
        ON DELETE SET NULL,
    CONSTRAINT fk_adjustment_requested_user
        FOREIGN KEY (requested_by_user_id) REFERENCES users(user_id)
        ON DELETE SET NULL,
    CONSTRAINT fk_adjustment_approved_user
        FOREIGN KEY (approved_by_user_id) REFERENCES users(user_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- =============================================
-- Purchase Orders table (Phase 7A)
-- =============================================
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id                INT PRIMARY KEY AUTO_INCREMENT,
    po_number            VARCHAR(20) NOT NULL UNIQUE,
    supplier_id          INT DEFAULT NULL,
    supplier_name        VARCHAR(100) NOT NULL,
    status               ENUM('draft','pending_approval','approved','partially_received','received','cancelled') DEFAULT 'draft',
    expected_delivery_date DATE DEFAULT NULL,
    subtotal             DECIMAL(10,2) DEFAULT 0.00,
    notes                TEXT DEFAULT NULL,
    created_by_user_id   INT DEFAULT NULL,
    created_by_name      VARCHAR(100) DEFAULT NULL,
    approved_by_user_id  INT DEFAULT NULL,
    approved_by_name     VARCHAR(100) DEFAULT NULL,
    approved_at          TIMESTAMP NULL DEFAULT NULL,
    created_at           TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_po_supplier
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        ON DELETE SET NULL,
    CONSTRAINT fk_po_created_user
        FOREIGN KEY (created_by_user_id) REFERENCES users(user_id)
        ON DELETE SET NULL,
    CONSTRAINT fk_po_approved_user
        FOREIGN KEY (approved_by_user_id) REFERENCES users(user_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- =============================================
-- Purchase Order Items table (Phase 7A)
-- =============================================
CREATE TABLE IF NOT EXISTS purchase_order_items (
    item_id            INT PRIMARY KEY AUTO_INCREMENT,
    po_id              INT NOT NULL,
    product_id         INT DEFAULT NULL,
    product_name       VARCHAR(100) NOT NULL,
    quantity_ordered   INT NOT NULL,
    unit_cost          DECIMAL(10,2) NOT NULL,
    quantity_received  INT DEFAULT 0,
    item_total         DECIMAL(10,2) GENERATED ALWAYS AS (quantity_ordered * unit_cost) STORED,
    CONSTRAINT fk_poi_po
        FOREIGN KEY (po_id) REFERENCES purchase_orders(po_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_poi_product
        FOREIGN KEY (product_id) REFERENCES products(product_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- =============================================
-- Company Info table (Phase 10 — PDF invoicing)
-- Single-row config table for branding
-- =============================================
CREATE TABLE IF NOT EXISTS company_info (
    id             INT PRIMARY KEY DEFAULT 1,
    company_name   VARCHAR(150) NOT NULL,
    address        VARCHAR(300) NOT NULL,
    phone          VARCHAR(30) NOT NULL,
    gst_number     VARCHAR(50) DEFAULT NULL,
    logo_path      VARCHAR(255) DEFAULT NULL,
    tagline        VARCHAR(150) DEFAULT NULL,
    invoice_format ENUM('thermal_80mm', 'a4') NOT NULL DEFAULT 'a4',
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
) ENGINE=InnoDB;

INSERT INTO company_info (id, company_name, address, phone, gst_number, logo_path, tagline)
VALUES (1, 'NovaTech Solutions',
        'Shop #12, Tech Plaza, Main Shahrah-e-Faisal, Karachi, Pakistan',
        '+92 300 1234567', 'GST-07-1234567-8',
        'static/uploads/company/logo.png', NULL)
AS new_row
ON DUPLICATE KEY UPDATE
    company_name = new_row.company_name,
    address      = new_row.address,
    phone        = new_row.phone,
    gst_number   = new_row.gst_number,
    logo_path    = new_row.logo_path,
    tagline      = new_row.tagline;
