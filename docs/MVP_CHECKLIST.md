# v0.1.8 MVP traceability

Inspected branch `work` at `fde4f93e0a26c0ce96a59cbfc219ee3e50f08d67` on 2026-10-04. Initial tests: 8 passed.

| Requirement | Final | UI | Route/service | Evidence |
|---|---|---|---|---|
| Public fixture filters/profiles | Working | home/profile/event | `/`, `/clubs`, `/venues`, `/competitions` | route tests and synthetic smoke test |
| Sales lifecycle enforcement | Working | event status and admin controls | `reserve`, `checkout`, fixture state routes | business tests |
| GA/assigned inventory | Working | visual seat checkboxes | `reserve` membership/capacity checks | business tests |
| Expiring reservations | Working | checkout expiry copy | active-hold queries | expiry/reuse test |
| Simulated checkout only | Working | TEST PAYMENT selector/results | `PaymentService` boundary | success/decline tests |
| Protected tickets | Working | access-bearing view/print links | order/ticket/QR access checks | route tests |
| Gate manual/wedge/photo | Working with hardware verification outstanding | gate camera/upload/manual controls | common `/gate/scan`; conditional atomic update | decode UI tests/manual procedure |
| Fixture administration | Working | create/detail/lifecycle forms | admin event routes | route tests |
| Search/cancel | Partial | search and idempotent cancellation | admin routes | integration checks; pagination and monetary partial refunds remain out of scope |
| Statistics/export | Working (core measures) | labelled fixture dashboard | persisted order/ticket aggregates and CSV | known synthetic scenario |
| Production migration/concurrency | Partial | n/a | SQL migration; SQLite atomic scan | SQLite checked; PostgreSQL and legacy reservation-table rebuild not exercised |

Camera launch is not proven by automated decoding. Physical Chrome/Safari/Firefox and phone hardware checks remain required. BarcodeDetector support varies; unsupported browsers receive a manual/wedge fallback rather than a false success claim.

## Supporter portal addition

Supporter registration, authentication, personal dashboards, club preferences,
age-based eligibility, disability concessions and consent-based admin reporting
are covered by route/business tests. Phil's specified test account and Glentoran
season record are created idempotently. Season passes and personally assigned
match tickets share a per-supporter/per-fixture admission guard. Password recovery,
email verification and physical proof of age
or disability are outside this demo portal; eligibility uses declared profile and
guest details. Season-pass admissions are separate from ticket-stock allocation.

## Match dashboard, cup claims and away allocation

Your Matches, Profile, consolidated Settings, Your Tickets and History have
separate supporter pages. Free cup claims preserve the official season category
and section, consume match inventory and have a unique season-ticket/fixture
constraint. Cup admission uses the claimed ticket QR. Away reservations verify
an account-owned away-club season ticket and revalidate it at checkout. Railway
Stand uses assigned seats; home and away Disabled tickets share the home Lower
Grandstand's physical capacity. Test numbers are documented and displayed at the
bottom of the relevant screens. Fixture capacities are demo allocations.

## Club administration and season sales

Global and club administrator roles have separate resource scopes across reads,
mutations, search, exports and protected ticket/QR views. Club management adds
profile settings, fixture amendment, inventory/type controls and audit activity.
Season issue creates a new supporter or links an existing account without
resetting credentials. Product-based issue and simulated purchases share capacity
limits; retries and duplicate entitlements cannot mint multiple passes. Initial
account credentials appear once with no-store response headers. Glentoran next
season Adult £250 / Concession £150 products demonstrate renewal for existing
customers. Email delivery, real payments and identity verification remain outside
the demo. New directory venue allocations are sample setup values.
