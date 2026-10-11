# Gateline v0.1.8

Gateline is a football-first, self-hosted ticket sales and gate validation system. This release supports the complete journey from inventory reservation and simulated payment to individual QR tickets, cancellation, scanning and live attendance.

## Stack
Python 3.12+, FastAPI, SQLAlchemy 2, SQLite (development; PostgreSQL via `DATABASE_URL`), Jinja, responsive CSS and QRCode. Payment processing is isolated behind `PaymentService` and v0.1.8 deliberately uses a labelled simulator.

## Start locally
```bash
uv sync
RESET_DEMO_DATABASE=1 uv run python scripts/seed.py
SECRET_KEY='replace-me' uv run uvicorn gateline.main:app --reload
```
Open http://127.0.0.1:8000. To retain data, do not re-run the destructive demo seed command. Production deployments must use HTTPS, a persistent `SECRET_KEY`, secure-cookie configuration and PostgreSQL.

### Staff login (local development only)
After seeding the database, open [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) and sign in with one of these demo staff accounts:

| Role | Email | Password | Access |
| --- | --- | --- | --- |
| Administrator | `admin@gateline.test` | `Admin123!` | Event dashboard, attendance, ticket search and cancellation |
| Gate operator | `gate@gateline.test` | `Gate123!` | Gate 1 ticket scanner |

These credentials are created by `scripts/seed.py` and must not be used in production.

### Other demo data
* Priority numbers: `ST001234`, `ST005678`
* 36 sample home fixtures across the 2026/27 NIFL Premiership and Championship,
  and the 2026 NIFL Women's Premiership
* All 36 clubs and their 28 home stadiums, including grounds shared across teams

### Club browsing
The fixture finder groups the supplied club directory into NIFL Premiership,
NIFL Championship, NCL Premier and NIFL Women's. Club selection uses a sidebar,
which collapses on mobile. Stadium and competition filters are small buttons above
the fixtures; there is no date filter or per-day match count. League sections collapse
to keep the picker compact; the selected club's league opens automatically. The
48 directory clubs, including Limavady United in the Premiership, remain browsable without published fixtures. Existing fixture
clubs outside this directory remain under Other clubs. Women's teams have
separate filter identities, and straight/curly apostrophes in Queen's University
resolve to the same fixtures. Directory stadium, location and capacity information
lives in `gateline/clubs.py`; it does not alter ticket inventory or existing venues.

Fixture cards show the minimum adult ticket price for that event, excluding child
and concession prices. Club, stadium and competition profile cards include the
fixture date and kick-off in Europe/London. Competition links support season names
containing slashes, such as `2026/27`.

### Ticket selection and reservations
Each club has a saved ticket menu in `club_pricing`. Administrators open **Club
pricing** from Match control to set named ticket types, prices and adult-admission
categories and concession age limits. New clubs start with Adult £15 and Concession
£8. Administrators can edit or remove these defaults; their saved menus persist
across restarts and retain club-specific types, including Glentoran and Linfield's
bespoke options. Saving prices updates upcoming home fixtures, while issued
tickets retain their recorded amounts. An explicitly empty menu disables sales.

Startup adds the new defaults once to existing menus that have not been explicitly
edited by a club administrator. Existing configured prices and bespoke types are
preserved. The old demo Concession £10 / Child £5 menu is replaced by the new
Adult / Concession defaults without deleting historical class records or tickets.
Ticket quantities start blank.
Public ticket pages do not display remaining stock; server capacity checks and
staff attendance statistics remain available.

Supporters can reserve a mixture of ticket types in one booking. Each Under 11
ticket requires at least one paid adult ticket in the same booking; no
adult-to-child ratio is imposed. Concession-only bookings do not qualify, and a
voucher that makes the accompanying adult ticket free is rejected for this child discount.
Glentoran VIP tickets cost £70, or £50 for the verified season-ticket holder's own
VIP ticket. Dedicated season-ticket records are club scoped, date limited and
linked to a supporter account; entering another person's number cannot claim the
discount. Guest VIP tickets keep their normal price. Legacy priority identifiers
remain compatible, with their existing entitlement limits consumed on successful
payment. VIP attendees must be 18 or older on match day. Under 11 tickets require
a date of birth for an attendee under 11. Eligibility is checked on the server.

### Supporter portal
Open `/register` to create an account, or `/account/login` to sign in with a
username or email. Accounts have a required date of birth and multiple followed
clubs. `/account` puts followed clubs first, shows availability notifications for
matches without valid tickets or season coverage, and lists bookings, sections,
distinct matches bought, active season tickets and matches actually attended.
Only new authenticated bookings belong to that account; matching a guest order's
email does not grant access. Mark one attendee as **This is my ticket** so their
saved age and access preferences apply and gate scans count personal attendance.
Guest attendees have separate eligibility details and never inflate the buyer's
attendance count. Ordinary Adult tickets remain purchasable at any age.

Concession defaults are strictly **under 16 or over 65**, evaluated on match day,
with editable club limits. The profile's **Force concession due to disability**
option permits concessions regardless of age. Dedicated disabled/accessibility
types appear first, then eligible concessions; Adult and other available tickets
remain selectable if a discounted option is unavailable. Optional disability type
and access details are shown to administrators of relevant matches only when the
supporter opts into sharing. Revoking consent immediately removes them from those
dashboards. Bookings for guests do not share the account holder's access needs.

The requested test identity is created once on startup and by the demo seed:
`philmcveigh` / `password123!`, Phil McVeigh, `phil.mcveigh@gateline.com`, born
17 March 1992, following Glentoran. The Glentoran season-ticket register contains
**12345**, **Sydenham End**, **Adult**, linked to this account. Its initial validity
is the current July–June season for home NIFL Premiership fixtures; cup and away
matches require separate tickets. Existing profile/password changes are preserved.
The account includes a printable season pass with its own QR code, and gate staff
can scan it or type the club-scoped season number. A unique supporter/fixture
attendance record prevents duplicate admission using a personal ticket and pass.
Season-pass admissions are reported separately from the existing ticket-stock
statistics; no stadium inventory allocation is inferred from a season section.
Administrators can open a club's **Season-ticket register** from its pricing page.

The additive portal schema migration is applied on startup. Operators managing
SQL manually can use `migrations/004_supporter_portal.sql`; the application then
initialises menus and the test record. This is a demo identity with the supplied
password, so disable it or change its password before any production deployment.

Selections and the existing reservation deadline persist across checkout reloads
and validation errors. The countdown disables payment when time runs out; the
server independently rejects expired or completed bookings. The normal hold is
10 minutes, shortened if sales close earlier. The additive reservation selection
column is upgraded automatically on startup; `migrations/002_reservation_ticket_selection.sql`
is provided for operators who apply SQL migrations manually.

New public ticket numbers start with a stable home-club identifier, such as
`GLENTORAN-` or `LINFIELD-`, followed by a random suffix. Every directory club has
a distinct prefix, including separate women’s teams; club aliases resolve to the
same prefix. Legacy ticket numbers and QR tokens are unchanged. The additive
`club_pricing`, `enabled` and `adult_admission` schema changes are applied at
startup, with `migrations/003_club_pricing.sql` for manual migration workflows.

## Database and migrations
The application creates a new schema on first start. Schema evolution lives in `migrations/`; for this initial baseline run the included SQL or the seed script. Set `DATABASE_URL=postgresql+psycopg://...` for PostgreSQL and install its driver.

## Tests
```bash
uv run pytest
```
Tests cover reservation exclusivity/capacity/expiry, priority and voucher enforcement, payment outcomes, individual ticket creation, scanning state transitions, cancellation/refunds/wrong events, and role restrictions.

## Structure
* `gateline/models.py` — relational domain model and constraints.
* `gateline/services.py` — transactional reservations, checkout/payment, discounts and validation.
* `gateline/main.py` — public, administration and restricted gate HTTP surfaces.
* `gateline/templates`, `gateline/static` — server-rendered responsive product UI.
* `scripts/seed.py` — demo fixtures for all clubs and stadiums in the seeded NIFL competitions.
* `tests/` — critical business rules.

## Current limitations and roadmap
v0.1.8 uses a test payment provider, browser print-to-PDF, online scanning, a single configured club, simple stand gate assignment and ten-minute lazy-expiry reservations. Email/SMS, wallets, offline/hardware scanning, season-ticket administration/renewals, verified identity/age checks, email verification/password recovery, resale, hospitality, accounting and dynamic pricing are intentionally excluded. Future releases can add a background expiry worker, Stripe/Worldpay adapters, PostgreSQL row locking, broader decoder compatibility, richer venue editing and multi-organisation tenancy without changing the core ticket lifecycle.

## v0.1.8 camera and HTTPS testing
Gate operators can use manual ticket entry, a keyboard-wedge scanner, native image capture/upload, or an in-page camera started explicitly with **Take QR photo**. Image decoding is local through the browser `BarcodeDetector`; unsupported browsers clearly fall back to manual/wedge entry. Photos are not uploaded or retained. Webcam APIs require HTTPS or trusted `localhost`—a phone visiting an ordinary `http://192.168.x.x` LAN address is **not** localhost.

For a local phone test, generate a trusted development certificate (for example with `mkcert`), run Uvicorn with `--ssl-keyfile` and `--ssl-certfile`, install/trust the development CA on the phone, and visit the computer's `https://<LAN-IP>:8000`. Check permission denial, rear-camera preference, upload/cancel, unreadable and multiple QR codes, duplicate scans, camera closure and session expiry. Physical camera launch is not established by automated tests.

## Upgrade and safety
Back up the database before upgrading. On startup Gateline applies the additive v0.1.8 columns to an existing database and generates access tokens for existing orders; it does not erase orders or tickets. `migrations/001_v0_1_8.sql` remains available for operators who manage schema changes separately and therefore disable application startup during deployment. Existing SQLite databases created before v0.1.8 also require a planned table rebuild to remove the legacy permanent `(event_id, seat_id)` reservation uniqueness constraint; do not wipe them. New installations receive the corrected schema. The demo seed is destructive and therefore intended only for a disposable development database; point `DATABASE_URL` at an isolated file before running it.

All payment outcomes are simulations: no provider, credentials, email delivery or real customer data should be used. This release has not been validated against PostgreSQL or production traffic and must not be represented as fully production-ready. See `docs/MVP_CHECKLIST.md` for verified and outstanding scope.
