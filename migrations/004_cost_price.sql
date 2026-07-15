-- ============================================================
-- Migration 004: Add cost_price to products
-- Adds cost_price column for profit tracking in Phase 11 reports.
-- Backfills from the most recent purchase_order_items.unit_cost
-- for each product that has been received via a PO.
-- Idempotent: safe to re-run.
-- ============================================================

-- 1. Add cost_price column (nullable — existing products won't have it yet)
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'products'
      AND COLUMN_NAME = 'cost_price');
SET @sql_add_col = IF(@col_exists = 0,
    'ALTER TABLE products ADD COLUMN cost_price DECIMAL(10,2) DEFAULT NULL AFTER price',
    'SELECT "Column cost_price already exists — skipping"');
PREPARE stmt1 FROM @sql_add_col;
EXECUTE stmt1;
DEALLOCATE PREPARE stmt1;

-- 2. Backfill cost_price from the most recent PO receipt per product.
--    Only updates products where cost_price is still NULL and PO history exists.
UPDATE products p
JOIN (
    SELECT poi.product_id, poi.unit_cost
    FROM purchase_order_items poi
    JOIN purchase_orders po ON poi.po_id = po.po_id
    WHERE poi.product_id IS NOT NULL
      AND po.status IN ('approved', 'partially_received', 'received')
      AND poi.unit_cost > 0
    ORDER BY po.updated_at DESC, po.po_id DESC
) latest ON p.product_id = latest.product_id
SET p.cost_price = latest.unit_cost
WHERE p.cost_price IS NULL;

-- 3. Report results
SELECT
    SUM(CASE WHEN cost_price IS NOT NULL THEN 1 ELSE 0 END) AS backfilled,
    SUM(CASE WHEN cost_price IS NULL THEN 1 ELSE 0 END) AS still_null,
    COUNT(*) AS total_products
FROM products;
