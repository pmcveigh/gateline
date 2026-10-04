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
* `scripts/seed.py` — immediately demonstrable Glentoran/The Oval data.
* `tests/` — critical business rules.

## Current limitations and roadmap
v0.1.8 uses a test payment provider, browser print-to-PDF, online scanning, a single configured club, simple stand gate assignment and ten-minute lazy-expiry reservations. Email/SMS, wallets, offline/hardware scanning, full season tickets, supporter accounts/CRM, resale, hospitality, accounting and dynamic pricing are intentionally excluded. Future releases can add a background expiry worker, Stripe/Worldpay adapters, PostgreSQL row locking, broader decoder compatibility, richer venue editing and multi-organisation tenancy without changing the core ticket lifecycle.

## v0.1.8 camera and HTTPS testing
Gate operators can use manual ticket entry, a keyboard-wedge scanner, native image capture/upload, or an in-page camera started explicitly with **Take QR photo**. Image decoding is local through the browser `BarcodeDetector`; unsupported browsers clearly fall back to manual/wedge entry. Photos are not uploaded or retained. Webcam APIs require HTTPS or trusted `localhost`—a phone visiting an ordinary `http://192.168.x.x` LAN address is **not** localhost.

For a local phone test, generate a trusted development certificate (for example with `mkcert`), run Uvicorn with `--ssl-keyfile` and `--ssl-certfile`, install/trust the development CA on the phone, and visit the computer's `https://<LAN-IP>:8000`. Check permission denial, rear-camera preference, upload/cancel, unreadable and multiple QR codes, duplicate scans, camera closure and session expiry. Physical camera launch is not established by automated tests.

## Upgrade and safety
Back up the database, then apply `migrations/001_v0_1_8.sql` once with the database CLI. It is additive and does not erase orders or tickets. Existing SQLite databases created before v0.1.8 also require a planned table rebuild to remove the legacy permanent `(event_id, seat_id)` reservation uniqueness constraint; do not wipe them. New installations receive the corrected schema. The demo seed is destructive and therefore intended only for a disposable development database; point `DATABASE_URL` at an isolated file before running it.

All payment outcomes are simulations: no provider, credentials, email delivery or real customer data should be used. This release has not been validated against PostgreSQL or production traffic and must not be represented as fully production-ready. See `docs/MVP_CHECKLIST.md` for verified and outstanding scope.
