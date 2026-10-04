-- Gateline v0.1.8 non-destructive SQLite upgrade. Back up the database first.
ALTER TABLE events ADD COLUMN sales_suspended BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE events ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN access_token VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_access_token ON orders(access_token);
-- SQLite cannot drop the old reservation uniqueness constraint in place. Rebuild
-- reservations following the documented migration procedure before production use.
