# LimoPlus — notes for AI agents

Interactive learning platform for Iranian university students: books per major (field of study), each with a
summary mode and a full-notes mode, plus tests, flashcards and study stats. The owner does not write code; agents
write and test it. The owner reads Persian; user-facing text, admin labels and docs for the owner are in Persian.
Code, identifiers and commit messages are in English.

## Layout

- `backend/` — Django 5.2 + DRF, PostgreSQL. Apps: `apps.accounts` (phone OTP login, device sessions),
  `apps.catalog` (majors, content tree via django-treebeard, banners), `apps.learning` (questions, choices,
  exam sources, flashcards, reports).
- `app/` — Expo (SDK 58) + TypeScript, one codebase for Android, web (PWA for iPhone users) and desktop browsers.
  Read `app/AGENTS.md` before touching Expo APIs.
- `docker-compose.yml` — local Postgres + backend.

## Rules that must hold

- **No secrets or host names in code.** Everything host-specific lives in `backend/.env` and `app/.env`
  (documented in the `.env.example` files). Moving to a real domain must only change those two files.
- **User data is never lost.** No hard deletes of purchases, progress, notes, scores or reports — use
  `is_archived` / soft delete. Every migration must be reversible and must not drop user data. Content edits must
  not break user data: highlights, progress and comments attach to stable ids, not to text.
- **Money is computed only on the server.** The app never sends prices or discount amounts. Payment verification
  compares the verified amount with the order. Wallet balance changes and order payment happen in one atomic
  transaction with row locks.
- **Auth:** phone + SMS code only (no passwords for learners). Codes and session tokens are stored as keyed hashes.
  OTP: 6 digits, 2 min lifetime, 5 attempts, 60 s resend cooldown, 5 codes/hour and 15 wrong guesses/day per
  phone, 20 requests and 30 wrong guesses/hour per IP. Limits are DB counters (`accounts.ratelimit`), shared by
  all processes. Client IP comes from REMOTE_ADDR or the entry added by our own proxies (`TRUSTED_PROXY_COUNT`),
  never the client-supplied part of X-Forwarded-For. The proxy must overwrite X-Forwarded-Proto.
  The SMS is sent after the code is committed. `SMS_BACKEND=console` is refused when DEBUG is off.
  At most `MAX_ACTIVE_SESSIONS` (2) devices per account; a third login must choose one to sign out.
- **Quiz answers are graded on the server**; correct answers are not sent before submission.
- Formulas are LaTeX rendered with KaTeX, always isolated left-to-right inside RTL text.
- Dates shown to users are Jalali (Persian calendar).

## Decided product details

Negative marking on by default in exam mode. Flashcards are key points (title front, point back), not questions,
and link to related questions. Each question has explanation + optional quick solution + alternative view, and
tags: exam sources (many), declared difficulty, measured difficulty (after 30 answers), domain, kind, topic.
Paid books can have free parts (`is_free` on any node). Pricing: single book purchase and monthly subscriptions
(prices editable in admin). Payment gateway: Zibal (`ZIBAL_MERCHANT`, test merchant `zibal` until the real one).
SMS: RayganSMS (`SMS_BACKEND=raygan`) or `console` for development. Banners: several, horizontal scroll, targeted
by major, never inside reading or quiz screens. AI assistant is shown as "coming soon" only.

## Workflow

- Work on a branch and open a pull request; the owner reviews before merge.
- Run before every PR: `cd backend && SECRET_KEY=test DEBUG=True python manage.py test apps` and
  `cd app && npm run typecheck`. Run backend management commands locally with `DEBUG=True`.
- In this cloud environment `npx expo install` cannot reach Expo's version API; pin versions manually and ask the
  owner to run `npx expo install --fix` locally if needed.
- Payment, auth and data-migration changes get an independent review before merge.
