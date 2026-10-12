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
| Away gate operator | `awaygate@gateline.test` | `AwayGate123!` | Gate 2 scanner for City End / Railway Stand |

These credentials are created by `scripts/seed.py` and must not be used in production.

### Other demo data
* Priority numbers: `ST001234`, `ST005678`
* 36 sample league home fixtures plus Glentoran v Linfield in the NIFL League Cup across the 2026/27 NIFL Premiership and Championship,
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
username or email. The default **Your Matches** dashboard (`/account`) shows
notifications first, then matches for followed clubs, existing bookings and season
entitlements, with all other fixtures below. **Profile** (`/account/profile`) holds
stats, season passes and section choices. All editable preferences, accessibility,
contact/address details and password changes are together in **Settings**
(`/account/settings`). **Your Tickets** (`/account/tickets`) opens bought and claimed
match tickets for printing; **History** (`/account/history`) lists successful/failed
bookings, claims and actual gate admissions. Email/password changes require the
current password. Matching a guest order's email never grants account ownership.

Mark one paid-booking attendee as **This is my ticket** so their saved age and access
preferences apply. Guest eligibility details are separate and guest scans do not
inflate the buyer's attendance count. Ordinary Adult tickets remain purchasable at
any age. Concession defaults are strictly **under 16 or over 65** on match day,
with editable club limits. **Force concession due to disability** is in Settings.
Dedicated Disabled/accessibility types appear first, then eligible concessions;
Adult and other types remain selectable if a discount is unavailable. Optional
disability/access details appear to relevant match administrators only with explicit,
revocable consent. Unclaimed cup entitlements do not share access needs as attendance.

### Glentoran v Linfield — NIFL League Cup
Startup and demo seeding add this fixture once at **The Oval**. The demonstration
kick-off is 15:00 Europe/London on the Saturday three weeks after the next/current
Saturday when first created (7 November 2026 if initialised on 12 October 2026).
Restarting does not change its date, prices, allocation or existing bookings.

Home season-ticket holders **must claim a match ticket**, even though it costs £0.
The registered section and ticket type determine the claim: Phil's ticket is
**Adult / Sydenham End**, never VIP or an away section. One claim is allowed per
season ticket per fixture; repeat requests return the existing ticket. Cancelled
claims require the club to arrange a replacement. Claims consume section inventory,
produce an individual protected QR ticket and require no payment or billing address.
Claimed matches have their own profile count rather than inflating paid-match stats.
Scan the **claimed match ticket**, not the season pass, for this cup fixture.
League fixtures retain their existing season-pass admission behavior.

Away fans sign in and verify an active, account-owned **Linfield** season-ticket
number to unlock the Glentoran away model: **Adult £15**, **Concession £8** and
**Disabled £8**. Away areas are **City End** (general admission) and **Railway Stand**
(assigned seating). Away access and section/class allocation are checked both when
reserving and at checkout. Home numbers and legacy priority identifiers cannot
unlock away tickets. Away prices stay separate from the home club menu.

**Disabled tickets cost £8 for home and away fans. Away Disabled seating at The Oval
is in the home section, Lower Grandstand.** Both use the same physical inventory,
so their capacity is shared; away standard tickets cannot be booked there. The
fixture uses sample allocations and unreserved Lower Grandstand seating for this
demo; these capacities do not represent audited stadium inventory.

### Test accounts, season-ticket and voucher numbers
The following demonstration identities and numbers are created idempotently.
Existing password/profile changes, code usage and season validity are preserved.
They are also shown as text at the bottom of relevant app screens (match booking,
checkout, sign-in, profile/settings, ticket/history and season-ticket windows).

| Test item | Number / code | Details |
| --- | --- | --- |
| Glentoran season ticket | `12345` | Phil McVeigh, `phil.mcveigh@gateline.com`, born 17 March 1992; Adult, Sydenham End. Login `philmcveigh` / `password123!`. Free home League Cup claim and own £50 VIP pricing. |
| Linfield season ticket | `LF12345` | Linfield Test Fan, `linfield.fan@gateline.test`, born 1 January 1990; Adult, South Stand Half Way Line. Login `linfieldfan` / `Linfield123!`. Unlocks paid away tickets for the cup fixture. |
| Legacy priority identifier | `ST001234` | 2 uses; does not unlock away access or free cup claims. |
| Legacy priority identifier | `ST005678` | 1 use; does not unlock away access or free cup claims. |
| Test voucher | `DEMO10` | 10% off paid test bookings, up to 100 uses, valid until the current July–June season ends. Free claims remain £0 and do not consume vouchers. |

Initial season-ticket validity is the current July–June season. Administrative
registers are under `/admin/clubs/{club}/season-tickets`. Printable season passes
have protected QR codes. A per-supporter/per-fixture admission record prevents
entering twice via personal tickets and season entitlements. The original portal
migration is `migrations/004_supporter_portal.sql`; the additional claim/audience
schema is `migrations/005_cup_claims_and_away_allocations.sql`. Both are applied
additively on startup. The supplied passwords and visibly listed codes are for
demo testing; remove/change them before production use.

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

## Club administration
Global administrators keep access to every club. Club administrators can manage
only their assigned club's details, hosted fixtures, match/season pricing, holders,
sales, ticket views, exports and activity. Being the away team does not grant
control of another club's fixture. Every admin read/write route checks ownership;
search results and QR/order access follow the same boundary. Supporter and gate
roles cannot use club management.

Club management is under `/admin/clubs`, separate from Match control. Clubs can
edit display/contact/address/description/colour details and their default venue.
Canonical identity and fixture ownership remain stable when display names change.
Directory stadiums missing from the demo database get a sample General Admission
section with capacity 1,000; these are setup examples, not audited ground limits.

Staff sign in at `/login` with username or email. Startup creates one demo club
administrator per directory/fixture club. Usernames are the lowercase club ticket
prefix plus `.admin` (long names use a stable shortened prefix); email adds
`@gateline.test`. The initial demo password is **`ClubAdmin123!`**. For example:

| Club | Username | Email |
| --- | --- | --- |
| Glentoran | `glentoran.admin` | `glentoran.admin@gateline.test` |
| Linfield | `linfield.admin` | `linfield.admin@gateline.test` |
| Cliftonville | `cliftonville.admin` | `cliftonville.admin@gateline.test` |

The global admin account `admin@gateline.test` / `Admin123!` remains available.
Global admins can inspect all club accounts and create additional administrators
at `/admin/club-accounts`; generated passwords appear once. Clubs change their
own password at `/admin/settings`. Existing credentials are never reset by startup.
These shared initial credentials are for demo testing and must be replaced before
production use.

Match control and club/holder lists have live text filters; fixture and holder
search also works on server submission. Search includes match orders/tickets,
season holders and season purchases within the administrator's scope. Club
activity records detail, fixture, inventory, pricing and season changes.

Club admins can create draft fixtures, amend title/opponent/competition/dates/
description and control publication/sales lifecycle. Section capacities, blocked
allocations, home/away audiences and per-fixture ticket types/prices/age limits are
editable. Capacity changes must accommodate issued tickets and active holds;
booked venues/claim policy and issued type allocations cannot be silently moved.
Shortened sales windows shorten live reservation deadlines. Published fixtures
still require inventory and enabled prices.

### Season holders and sales
`/admin/clubs/{club}/season-tickets/new` issues a product-based or custom pass. A
new supporter email creates a supporter account, date-of-birth profile and club
interest, with a generated username/password displayed **once** in a non-cached
response. Give these details to the holder; the app does not send email. An
existing supporter email links its account without changing its name, date of
birth, password or preferences. Staff identities cannot be converted into holders.
Issuance retries return the same pass. Clubs can view/print their holders' QR passes,
suspend/reactivate passes and search by name, email, number or section.

Generated pass numbers begin with the club prefix, e.g. `GLENTORAN-ST-`, and a
random suffix. Existing test numbers `12345` and `LF12345` and voucher `DEMO10`
remain documented above and visible in their relevant app windows.

Season products are managed at `/admin/clubs/{club}/season-products`: section,
category, competition, validity, price, capacity, concession limits and an app-sale
switch. Existing passes retain allocation/dates and purchase totals. Direct issue
and successful app purchases consume product capacity atomically; declined test
payments consume none. Overlapping passes and duplicate requests are rejected or
return the original receipt. Product quantities are separate from match inventory.

**Glentoran example:** next-season Sydenham End products start at **Adult £250** and
**Concession £150** (2027/28 when initialised in October 2026). Phil can renew using
his existing account; his current 2026/27 pass is preserved. The admin catalogue
provides a customer purchase URL (`/season-tickets/products/{id}`), and the club
profile links available products. Staff can preview the offer; only supporters can
purchase it. Customer purchases use the existing explicit **test payment** model,
check saved age/disability eligibility, create a QR season pass linked to the same
account and appear in purchase history and club sales tracking. No real payment
provider or email delivery has been added.

Run `migrations/006_club_administration_and_season_sales.sql` once if managing SQL
manually. Application startup upgrades the schema, backfills legacy fixture
ownership, adds club accounts and creates the example products idempotently.

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
v0.1.8 uses a test payment provider, browser print-to-PDF, online scanning, a single configured club, simple stand gate assignment and ten-minute lazy-expiry reservations. Email/SMS, wallets, offline/hardware scanning, verified identity/age checks, email verification/password recovery, resale, hospitality, accounting and dynamic pricing are intentionally excluded. Future releases can add a background expiry worker, Stripe/Worldpay adapters, PostgreSQL row locking, broader decoder compatibility, richer venue editing and multi-organisation tenancy without changing the core ticket lifecycle.

## v0.1.8 camera and HTTPS testing
Gate operators can use manual ticket entry, a keyboard-wedge scanner, native image capture/upload, or an in-page camera started explicitly with **Take QR photo**. Image decoding is local through the browser `BarcodeDetector`; unsupported browsers clearly fall back to manual/wedge entry. Photos are not uploaded or retained. Webcam APIs require HTTPS or trusted `localhost`—a phone visiting an ordinary `http://192.168.x.x` LAN address is **not** localhost.

For a local phone test, generate a trusted development certificate (for example with `mkcert`), run Uvicorn with `--ssl-keyfile` and `--ssl-certfile`, install/trust the development CA on the phone, and visit the computer's `https://<LAN-IP>:8000`. Check permission denial, rear-camera preference, upload/cancel, unreadable and multiple QR codes, duplicate scans, camera closure and session expiry. Physical camera launch is not established by automated tests.

## Upgrade and safety
Back up the database before upgrading. On startup Gateline applies the additive v0.1.8 columns to an existing database and generates access tokens for existing orders; it does not erase orders or tickets. `migrations/001_v0_1_8.sql` remains available for operators who manage schema changes separately and therefore disable application startup during deployment. Existing SQLite databases created before v0.1.8 also require a planned table rebuild to remove the legacy permanent `(event_id, seat_id)` reservation uniqueness constraint; do not wipe them. New installations receive the corrected schema. The demo seed is destructive and therefore intended only for a disposable development database; point `DATABASE_URL` at an isolated file before running it.

All payment outcomes are simulations: no provider, credentials, email delivery or real customer data should be used. This release has not been validated against PostgreSQL or production traffic and must not be represented as fully production-ready. See `docs/MVP_CHECKLIST.md` for verified and outstanding scope.
