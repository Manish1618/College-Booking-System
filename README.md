# College Guesthouse Booking System

One web portal for requesting, approving, allotting and billing college guesthouse rooms.
It replaces the paper and email process: guests see availability and raise a request, an approver
decides in one click, and the guesthouse office allots rooms with a database guarantee that no room
is ever booked twice for the same night.

## Run it

You need Docker with the Compose plugin.

```bash
cp .env.example .env
docker compose up --build
docker compose exec backend python manage.py seed_demo   # demo rooms, prices and staff users
```

Open <http://localhost:8080>. Sign in with any of the seeded addresses. In development the
sign-in code is shown on screen (`OTP_DEBUG_ECHO=true`), so no mail server is needed.

| Address | Role |
| --- | --- |
| `faculty@college.example.edu` | College requester |
| `registrar@college.example.edu` | Approver |
| `manager@college.example.edu` | Guesthouse manager (sets up an authenticator app at first sign-in) |
| `admin@college.example.edu` | Super admin (same) |
| any other email or mobile number | External guest |

To try the whole flow: as faculty pick dates (starting today, so the guest can be checked in) and
request a room, as registrar approve it, as faculty pay with the test payment button, then as manager
allot a room from **All bookings**, check the guest in and out from **Desk**, and look at **Register**.
Cancel a paid booking to see a refund become due on the desk screen.
On a paid booking choose **Change dates** to send new dates for approval, block a room for repairs at the
bottom of **Rooms**, and open **Reports** as manager to see occupancy and money for the month.

## What is built

This covers Phase 1 (foundation), Phase 2 (booking core), Phase 3 (desk and billing) and Phase 4
(changes of dates, reports and maintenance blocks) of the PRD.

| Area | State |
| --- | --- |
| Sign-in | Email or phone OTP, college-domain emails become college members, OIDC SSO behind `OIDC_ENABLED`, TOTP for manager and admin, no passwords stored |
| Roles | Requester, external guest, approver, manager, super admin, with role and ownership checks on every API view |
| Rooms | Room types, rooms, amenities and active status, editable by staff |
| Prices | Tariffs with an effective-from date; a booking keeps the price it was made at |
| Photos | Upload, reorder, replace, delete and cover photo; resized to three WebP widths by a Celery job |
| Availability | Date-range search by room type; shows counts only, never guest names |
| Booking request | Guests, stay category, purpose, recommendation letter (official) or student link (personal), guest ID copies |
| Approval | Routing rules by stay category; approve, reject or send back with a comment |
| Holds and expiry | 48-hour hold on a request, 24-hour payment window, no-show after noon the next day (Celery beat) |
| Allotment | Manager assigns a room; overlaps are rejected by a PostgreSQL exclusion constraint |
| Notifications | Email on every state change, SMS for sign-in codes and confirmations (console backends until providers are chosen) |
| Audit log | Append-only, enforced by a database trigger, readable by the super admin |
| Payments | One gateway interface with three adapters: a simulated gateway, Razorpay and MobiKwik. A booking is confirmed only by the gateway's signed webhook or a server-to-server lookup, never by the browser |
| Refunds | Cancelling a paid booking proposes the refund the rules allow. The manager sends it through the gateway, records one returned by hand, or gives one outside the rules |
| Check-in and check-out | The desk ticks each arriving guest after comparing the ID with the uploaded copy. Guests on one booking can arrive at different times. A **Desk** screen lists arrivals, departures, guests in house and refunds to send |
| Guest register | Numbered entries written at check-in; searchable, printable, CSV and PDF export; every view and export is logged |
| Receipts | A PDF with the booking ID and payment reference, attached to the confirmation email and downloadable later |
| Change of dates | Before check-in, the guest or the desk can ask for new dates. An unpaid request takes the new dates and goes back for approval. A paid booking keeps its dates and its room until the approver agrees, and until any balance is paid; a cheaper stay proposes a refund of the difference |
| Maintenance blocks | A manager takes a room out of service for a date range with a reason. A blocked room is not sold or offered for allotment, and the database refuses a block over a stay allotted to that room |
| Reports | A **Reports** screen for manager and admin: occupancy by day and by room type, money received and refunded by gateway, approvals waiting and decided, and no-shows, for any range up to a year, with a day-by-day CSV |

Not built yet: the hardening and launch work listed under "Known gaps".

## How it is put together

```
Browser -> Caddy -> Next.js (pages)
                 -> Django (/api, /django-admin) -> PostgreSQL
                                                 -> Redis -> Celery worker and beat
```

```
backend/    Django + Django REST Framework
  apps/accounts       users, roles, OTP, TOTP, OIDC backend, permissions
  apps/rooms          room types, rooms, tariffs, photos, upload checks
  apps/bookings       bookings, guests, documents, approvals, state machine, availability
  apps/payments       gateway adapters, webhooks, refunds, receipts, reconciliation
  apps/audit          append-only audit log
  apps/notifications  email and SMS tasks
  tests/              pytest suite
frontend/   Next.js (App Router), TypeScript, Tailwind CSS
Caddyfile, docker-compose.yml, .github/workflows/ci.yml
```

### The no-double-booking rule

`bookings.Booking` carries the constraint from the PRD, created by the first migration together with
the `btree_gist` extension:

```sql
EXCLUDE USING gist (room_id WITH =, daterange(check_in, check_out, '[)') WITH &&)
  WHERE (room_id IS NOT NULL AND status IN ('ALLOTTED', 'CHECKED_IN'))
```

Before that point, a request can only be submitted while a room of its type is free. That count runs
inside a transaction that locks the room type row, so two guests cannot both take the last room. Both
races have tests that run real concurrent transactions.

### Booking states

```
DRAFT -> PENDING -> APPROVED -> CONFIRMED -> ALLOTTED -> CHECKED_IN -> CHECKED_OUT
            |-> SENT_BACK -> PENDING
            |-> REJECTED
any state before check-in -> CANCELLED;  unapproved or unpaid in time -> EXPIRED;  not arrived -> NO_SHOW
```

Every change goes through `apps/bookings/state.py`, which validates the move, writes the audit entry
and queues the notification. `DRAFT` is an addition to the PRD's list: it lets a guest save the form,
attach documents and then submit, and it holds no room.

### Payments

`apps/payments/gateways.py` holds one adapter per gateway behind the same five calls: open an order,
say what the browser needs, turn a webhook into verified events, look a payment up, and refund.
`apps/payments/services.py` is the only code that marks anything paid, and it does so only from an
event an adapter has verified.

- **Webhooks** arrive at `/api/payments/webhooks/<gateway>`. The signature is checked against the raw
  body before anything is parsed, the amount must equal our own order record, and each gateway event is
  recorded so a repeated delivery changes nothing. The endpoint for a gateway does not exist until its
  secret is set.
- **A late webhook** is covered three ways: the pay screen asks the server to look the order up, a
  job re-checks open orders every 15 minutes, and a nightly job compares every recent payment with the
  gateway and emails the managers about any that disagree.
- **Money that cannot confirm a booking** (the request expired first, the room went, a second payment,
  a wrong amount) never confirms it. A paid order becomes a refund due on the desk screen.
- **Refunds** are marked as "with the gateway" before the gateway is called, so one refund cannot be
  sent twice. If the gateway does not answer, the refund is not assumed to have failed: a job looks it
  up and either settles it or frees it to be sent again.

| Gateway | State |
| --- | --- |
| `dev` | Simulated. It signs its own webhooks so the real verification path runs. On by default in development |
| `razorpay` | Orders, Standard Checkout, webhooks and refunds, written against Razorpay's current API reference. Not yet run against a live or test Razorpay account |
| `mobikwik` | MobiKwik's gateway, Zaakpay: redirect checkout, status lookup, webhook and refunds, written against Zaakpay's current documentation. Not yet run against a Zaakpay account |

Both real adapters are covered by tests that play back the documented responses, but neither has
handled real money. Run each against the gateway's test mode with the college's keys before go-live.
`.env.example` says which keys each needs and which webhook URL to register.

## Development without Docker

You need Python 3.13, Node 22, PostgreSQL 16 and Redis.

```bash
cp .env.example .env        # then point DATABASE_URL and REDIS_URL at localhost, set SITE_URL to :3000

cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate && python manage.py seed_demo
python manage.py runserver 8000            # API
celery -A config worker -B -l info         # emails, photo resizing, expiry jobs (second terminal)

cd ../frontend
npm ci && npm run dev                      # http://localhost:3000, proxies /api to Django
```

### Checks

```bash
cd backend
pytest --cov=apps                 # 209 tests; needs PostgreSQL and the Pango libraries (see below)
ruff check . && ruff format --check .
bandit -q -r apps config -ll
pip-audit -r requirements.txt

cd ../frontend
npm run lint && npx tsc --noEmit && npm run build
```

Receipts and the register PDF are drawn by WeasyPrint, which needs the Pango text libraries. The
Docker image installs them. Outside Docker, on Debian or Ubuntu:
`apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core`.

CI runs all of these on every push, builds both images and scans them with Trivy. Dependabot watches
pip, npm, Docker and Actions. Backend dependencies are pinned in `requirements.txt`, compiled from
`requirements.in` with `uv pip compile`.

## Configuration

Everything is set through environment variables; `.env.example` lists them all with comments.
The ones that need a decision before go-live:

| Setting | Default | Meaning |
| --- | --- | --- |
| `COLLEGE_EMAIL_DOMAINS` | `college.example.edu` | Emails on these domains sign in as college members |
| `OIDC_ENABLED` and `OIDC_*` | off | College SSO, once the IT cell issues a client ID and endpoints |
| `STAFF_MFA_REQUIRED` | `true` | Authenticator app for manager and admin |
| `BOOKING_HOLD_HOURS` / `PAYMENT_WINDOW_HOURS` | 48 / 24 | Hold on a request, and time to pay after approval |
| `BOOKING_MAX_NIGHTS` / `BOOKING_MAX_ADVANCE_DAYS` | 14 / 180 | Limits on a stay |
| `PAYMENT_GATEWAYS` | `dev` when `DEBUG` is on, otherwise empty | Any of `razorpay`, `mobikwik`, `dev`. The server refuses to start with `dev` when `DEBUG` is off |
| `RAZORPAY_*`, `MOBIKWIK_*` | empty | Gateway keys. Required for each gateway listed above |
| `REFUND_FULL_HOURS` / `REFUND_PARTIAL_HOURS` / `REFUND_PARTIAL_PERCENT` | 48 / 24 / 50 | Refund on a guest's cancellation, by hours before arrival |
| `REFUND_NO_SHOW_PERCENT` | 0 | Refund proposed for a no-show |
| `CHECK_IN_HOUR` | 12 | Arrival time the refund hours are counted back from |
| `DATE_CHANGE_MIN_HOURS` | 48 | A guest can change the dates of a paid booking online until this many hours before arrival. The desk can ask for a change until check-in |
| `S3_ENABLED` and `S3_*` | off | Private encrypted bucket for letters, ID copies and photo originals |
| `EMAIL_BACKEND`, `SMS_BACKEND` | console | Real mail server and SMS provider |
| `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` | empty | Set both to put the Cloudflare Turnstile check on the sign-in form |

For production set `DEBUG=false`, a long random `SECRET_KEY`, `OTP_DEBUG_ECHO=false`, the real domain
in `SITE_ADDRESS`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, and start with
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.

## Assumptions to confirm

The PRD leaves these open. Each has a working default so the build is not blocked.

| Question | What the code does now |
| --- | --- |
| Site wording (name, headline, booking steps, contact) | Defaults in `SiteContent`. Managers change it on the **Website** screen |
| Rooms, room types and prices | Three placeholder types with 12 rooms from `seed_demo`. Staff replace them on the **Rooms** screen |
| Who approves which stays | Any approver can decide any request until the admin adds approval rules per stay category |
| Which guardians are eligible | Any signed-in user can raise a personal stay; the approver judges the student link |
| Student records check | No records source is connected, so the approver screen says to check by hand |
| Are official stays paid | Every booking is charged room price times nights; no department billing or free stays |
| Refund rules | Full refund when the guest cancels 48 hours or more before noon on the arrival date, half from 48 down to 24 hours, nothing later, nothing for a no-show. The desk can refund in full when the guesthouse cancels. Every number is a setting |
| Who issues refunds | Nothing is refunded automatically. The rules propose an amount and the manager sends it, and may change it |
| Payment gateway accounts | Razorpay and MobiKwik are both built. Which one the college signs up for, and its keys, are still needed |
| Check-in window | A booking can be checked in from its arrival date until the day before check-out. Not every guest on a booking has to arrive, and those who come later are checked in from the same booking until check-out |
| Register contents | Name, phone, address, ID type, room, arrival, departure, purpose and amount. The ID number itself is not stored |
| Changing a paid booking | The booking is not touched until the change is approved, so a refusal or a slow answer never costs the guest a confirmed stay. The new stay is priced at the tariff in force on its check-in date. A higher price must be paid within the payment window (24 hours) or the change lapses; a lower price proposes a refund of the difference. Only the dates can change, not the room type |
| How late a guest can change dates | Online until 48 hours before noon on the arrival date, the same point at which a full refund stops, so moving a stay is not a way round the refund rules. After that the desk can still ask for a change on the guest's behalf, and it still needs approval |
| Who approves a change of dates | The same approvers as for a new request. A change can be approved or rejected, not sent back |
| Blocking a room on a full night | The manager is warned that a booking would be left without a room and can go ahead anyway (a burst pipe does not wait). The booking is not moved or cancelled automatically |
| What counts as occupancy and revenue | A night is sold once the stay is paid for. Rooms on offer are the rooms active today minus those blocked that night; there is no history of when rooms were added or retired. Money is counted on the day it was received or refunded, not on the day of the stay |
| Retention period | Nothing is auto-deleted yet. Needs the college's period before go-live |
| College SSO | Not connected. College-domain email OTP is the fallback, as the PRD allows |
| Hosting provider | Nothing is provider-specific. Any VM with Docker and an S3-compatible bucket works |

## Known gaps before go-live

- Local file storage is not encrypted. Production must set `S3_ENABLED=true` with a private bucket
  (server-side encryption is requested on every private upload).
- Rate limiting is in the app only. Limits at Caddy, the Cloudflare-only origin firewall and a strict
  Content Security Policy for the Next.js pages belong to the hardening phase.
- SMS goes to the log until a provider is chosen.
- Razorpay and MobiKwik have not been run against real accounts (see "Payments" above).
- A payment reported with an amount different from the order is marked failed and logged, and no refund
  is proposed for it. Staff check it in the gateway's dashboard and settle it by hand.
- A refund made in a gateway's own dashboard is not picked up. Record it on the booking as returned by hand.
- Availability is counted per room type. Heavy use of manually chosen rooms can, in rare cases, leave
  a type with a free night-by-night count but no single room free for the whole stay; the manager would
  then move an existing allotment. Automatic re-packing is not implemented.
