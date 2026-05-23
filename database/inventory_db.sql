-- =============================================
-- Database: inventory_db
-- =============================================
CREATE DATABASE IF NOT EXISTS inventory_db;
USE inventory_db;

-- =============================================
-- Create suppliers table
-- =============================================
CREATE TABLE suppliers (
    supplier_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100) UNIQUE,
    address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =============================================
-- Create products table
-- =============================================
CREATE TABLE products (
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    price DECIMAL(10,2) NOT NULL,
    stock_quantity INT DEFAULT 0,
    supplier_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_product_supplier
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- =============================================
-- Create sales table
-- =============================================
CREATE TABLE sales (
    sale_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    quantity_sold INT NOT NULL,
    sale_price DECIMAL(10,2) NOT NULL,
    total_amount DECIMAL(10,2) GENERATED ALWAYS AS (quantity_sold * sale_price) STORED,
    sale_date DATE NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sale_product
        FOREIGN KEY (product_id) REFERENCES products(product_id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- =============================================
-- Trigger: Auto-deduct stock on new sale
-- =============================================
CREATE TRIGGER trg_reduce_stock AFTER INSERT ON sales FOR EACH ROW UPDATE products SET stock_quantity = stock_quantity - NEW.quantity_sold WHERE product_id = NEW.product_id;

-- =============================================
-- Insert sample data: suppliers
-- =============================================
INSERT INTO suppliers (name, contact_person, phone, email, address) VALUES
('Tech Distributors Inc.', 'John Smith', '(555) 123-4567', 'john.smith@techdist.com', '123 Industrial Pkwy, Chicago, IL 60607'),
('Global Electronics Ltd.', 'Sarah Johnson', '(555) 234-5678', 'sarah.j@globalelec.com', '456 Commerce Blvd, Austin, TX 78701'),
('Office Supply Co.', 'Michael Brown', '(555) 345-6789', 'michael.brown@officesupply.com', '789 Market St, Denver, CO 80202'),
('Premium Parts Warehouse', 'Emily Davis', '(555) 456-7890', 'emily.davis@premiumparts.com', '321 Distribution Way, Seattle, WA 98101'),
('Value Electronics', 'David Wilson', '(555) 567-8901', 'david.wilson@valueelec.com', '654 Logistics Dr, Atlanta, GA 30303');

-- =============================================
-- Insert sample data: products
-- =============================================
INSERT INTO products (name, description, category, price, stock_quantity, supplier_id) VALUES
('Laptop Pro X15', 'High-performance laptop with 16GB RAM, 512GB SSD', 'Electronics', 1299.99, 50, 1),
('Wireless Mouse M3', 'Ergonomic wireless mouse with dual connectivity', 'Accessories', 29.99, 200, 1),
('Monitor 27" 4K', '27-inch 4K UHD monitor with HDR support', 'Electronics', 449.99, 35, 2),
('Office Desk Chair', 'Ergonomic mesh office chair with lumbar support', 'Furniture', 189.99, 25, 3),
('USB-C Hub 7-in-1', 'Multiport USB-C hub with HDMI, USB, Ethernet', 'Accessories', 59.99, 150, 4);

-- =============================================
-- Insert sample data: sales
-- (Trigger will auto-deduct stock on each insert)
-- =============================================
INSERT INTO sales (product_id, quantity_sold, sale_price, sale_date, notes) VALUES
(1, 3, 1299.99, '2024-01-15', 'Bulk order for corporate client'),
(2, 25, 29.99, '2024-01-18', 'Office supply restock'),
(3, 5, 449.99, '2024-01-20', 'Graphic design department purchase'),
(1, 2, 1299.99, '2024-01-22', 'Individual customer purchase'),
(5, 15, 59.99, '2024-01-25', 'IT department bulk order');

-- =============================================
-- Create bills table
-- =============================================
CREATE TABLE bills (
    bill_id INT PRIMARY KEY AUTO_INCREMENT,
    bill_number VARCHAR(20) NOT NULL UNIQUE,
    bill_date DATE NOT NULL,
    discount_percent DECIMAL(5,2) DEFAULT 0,
    subtotal DECIMAL(10,2) NOT NULL,
    discount_amount DECIMAL(10,2) GENERATED ALWAYS AS (subtotal * discount_percent / 100) STORED,
    grand_total DECIMAL(10,2) GENERATED ALWAYS AS (subtotal - (subtotal * discount_percent / 100)) STORED,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =============================================
-- Create bill_items table
-- =============================================
CREATE TABLE bill_items (
    item_id INT PRIMARY KEY AUTO_INCREMENT,
    bill_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    item_total DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    CONSTRAINT fk_billitem_bill FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    CONSTRAINT fk_billitem_product FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- =============================================
-- Trigger: Auto-deduct stock on bill item insert
-- =============================================
CREATE TRIGGER trg_bill_reduce_stock AFTER INSERT ON bill_items FOR EACH ROW UPDATE products SET stock_quantity = stock_quantity - NEW.quantity WHERE product_id = NEW.product_id;