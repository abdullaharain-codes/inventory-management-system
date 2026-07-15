-- ============================================================
-- Migration 003: PO Receive Support
-- Adds columns and ENUM values for the PO receive workflow.
-- Idempotent: safe to re-run on a DB that already has changes.
-- ============================================================

-- 1. Add quantity_received to purchase_order_items (if missing)
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'purchase_order_items'
      AND COLUMN_NAME = 'quantity_received');
SET @sql_add_col = IF(@col_exists = 0,
    'ALTER TABLE purchase_order_items
     ADD COLUMN quantity_received INT DEFAULT 0 AFTER unit_cost,
     ADD COLUMN item_total DECIMAL(10,2) GENERATED ALWAYS AS (quantity_ordered * unit_cost) STORED AFTER unit_cost',
    'SELECT "Column quantity_received already exists — skipping"');
PREPARE stmt FROM @sql_add_col;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. Ensure 'partially_received' is in the purchase_orders.status ENUM
SET @enum_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'purchase_orders'
      AND COLUMN_NAME = 'status'
      AND COLUMN_TYPE LIKE '%partially_received%');
SET @sql_alter_enum = IF(@enum_exists = 0,
    'ALTER TABLE purchase_orders
     MODIFY COLUMN status ENUM("draft","pending_approval","approved","partially_received","received","cancelled") DEFAULT "draft"',
    'SELECT "ENUM value partially_received already exists — skipping"');
PREPARE stmt2 FROM @sql_alter_enum;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

-- 3. Ensure 'purchase_receive' is in the stock_ledger.movement_type ENUM
SET @sl_enum_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'stock_ledger'
      AND COLUMN_NAME = 'movement_type'
      AND COLUMN_TYPE LIKE '%purchase_receive%');
SET @sql_sl_enum = IF(@sl_enum_exists = 0,
    'ALTER TABLE stock_ledger
     MODIFY COLUMN movement_type ENUM("sale","bill_sale","refund","adjustment","purchase","purchase_receive","opening_balance") NOT NULL',
    'SELECT "ENUM value purchase_receive already exists in stock_ledger — skipping"');
PREPARE stmt3 FROM @sql_sl_enum;
EXECUTE stmt3;
DEALLOCATE PREPARE stmt3;
