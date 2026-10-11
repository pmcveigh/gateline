-- Run once when managing schema changes manually; startup applies these safely.
CREATE TABLE IF NOT EXISTS club_pricing (club_name VARCHAR(150) PRIMARY KEY, menu_json TEXT NOT NULL);
ALTER TABLE ticket_classes ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE ticket_classes ADD COLUMN adult_admission BOOLEAN;
-- Issued tickets retain their IDs and prices. Initialise menus through startup.
