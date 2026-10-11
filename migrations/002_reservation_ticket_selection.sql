-- Add mixed ticket selections while retaining existing reservations and orders.
ALTER TABLE reservations ADD COLUMN selection_json TEXT NOT NULL DEFAULT '{}';
