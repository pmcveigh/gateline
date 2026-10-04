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
