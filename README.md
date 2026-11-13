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

To try the whole flow: as faculty pick dates and request a room, as registrar approve it, as faculty
pay with the test payment button, then as manager allot a room from **Desk**.

## What is built

This covers Phase 1 (foundation) and Phase 2 (booking core) of the PRD.

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

Not built yet (Phase 3 onwards): Razorpay and MobiKwik checkout and refunds, check-in and check-out,
the guest register screens, receipt PDFs, cancel-and-modify with re-approval, dashboards, maintenance blocks.
The `Payment` and `RegisterEntry` tables already exist so those phases need no schema rework.

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
  apps/payments       payment records (real gateways arrive in Phase 3)
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
pytest --cov=apps                 # 109 tests; needs PostgreSQL
ruff check . && ruff format --check .
bandit -q -r apps config -ll
pip-audit -r requirements.txt

cd ../frontend
npm run lint && npx tsc --noEmit && npm run build
```

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
| `PAYMENT_GATEWAYS` | `dev` in the example file, empty in code | `dev` is a simulated payment; remove it in production |
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
| Rooms, room types and prices | Three placeholder types with 12 rooms from `seed_demo`. Staff replace them on the **Rooms** screen |
| Who approves which stays | Any approver can decide any request until the admin adds approval rules per stay category |
| Which guardians are eligible | Any signed-in user can raise a personal stay; the approver judges the student link |
| Student records check | No records source is connected, so the approver screen says to check by hand |
| Are official stays paid | Every booking is charged room price times nights; no department billing or free stays |
| Refund rules | Cancelling releases the room. No refund is calculated yet (Phase 3) |
| Retention period | Nothing is auto-deleted yet. Needs the college's period before go-live |
| College SSO | Not connected. College-domain email OTP is the fallback, as the PRD allows |
| Hosting provider | Nothing is provider-specific. Any VM with Docker and an S3-compatible bucket works |

## Known gaps before go-live

- Local file storage is not encrypted. Production must set `S3_ENABLED=true` with a private bucket
  (server-side encryption is requested on every private upload).
- Rate limiting is in the app only. Limits at Caddy, the Cloudflare-only origin firewall and a strict
  Content Security Policy for the Next.js pages belong to the hardening phase.
- SMS goes to the log until a provider is chosen.
- Availability is counted per room type. Heavy use of manually chosen rooms can, in rare cases, leave
  a type with a free night-by-night count but no single room free for the whole stay; the manager would
  then move an existing allotment. Automatic re-packing is not implemented.
