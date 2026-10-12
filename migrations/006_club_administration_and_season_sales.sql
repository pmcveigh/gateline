-- Run once after migration 005 if managing schema manually.
-- Startup applies these columns and creates new tables automatically.
ALTER TABLE users ADD COLUMN managed_club VARCHAR(150);
ALTER TABLE events ADD COLUMN owner_club VARCHAR(150);
CREATE TABLE IF NOT EXISTS club_management (
	club_name VARCHAR(150) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	display_name VARCHAR(150) NOT NULL, 
	short_name VARCHAR(30) NOT NULL, 
	contact_email VARCHAR(200) NOT NULL, 
	address TEXT NOT NULL, 
	description TEXT NOT NULL, 
	primary_colour VARCHAR(7) NOT NULL, 
	venue_id INTEGER, 
	PRIMARY KEY (club_name), 
	FOREIGN KEY(venue_id) REFERENCES venues (id)
);

CREATE TABLE IF NOT EXISTS season_products (
	id INTEGER NOT NULL, 
	club_name VARCHAR(150) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	section VARCHAR(100) NOT NULL, 
	ticket_type VARCHAR(100) NOT NULL, 
	competition VARCHAR(150) NOT NULL, 
	valid_from DATE NOT NULL, 
	valid_until DATE NOT NULL, 
	price NUMERIC(10, 2) NOT NULL, 
	capacity INTEGER NOT NULL, 
	issued INTEGER NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	concession_under INTEGER NOT NULL, 
	concession_over INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(club_name) REFERENCES club_management (club_name)
);

CREATE TABLE IF NOT EXISTS season_purchases (
	id INTEGER NOT NULL, 
	reference VARCHAR(40) NOT NULL, 
	token VARCHAR(100) NOT NULL, 
	user_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	season_ticket_id INTEGER, 
	total NUMERIC(10, 2) NOT NULL, 
	payment_status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (reference), 
	UNIQUE (token), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(product_id) REFERENCES season_products (id), 
	FOREIGN KEY(season_ticket_id) REFERENCES season_tickets (id)
);

ALTER TABLE season_tickets ADD COLUMN product_id INTEGER REFERENCES season_products(id);
ALTER TABLE season_tickets ADD COLUMN issuance_token VARCHAR(100);
CREATE UNIQUE INDEX IF NOT EXISTS ix_season_issuance_token ON season_tickets(issuance_token);
CREATE UNIQUE INDEX IF NOT EXISTS ix_season_product_user ON season_tickets(product_id,user_id);
-- Initialise ownership, club accounts and the Glentoran example through startup.
