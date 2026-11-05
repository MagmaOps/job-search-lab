# Job Search Lab

Personal AI job-search app for landing a **remote EU DevOps role**. Single user, homelab.
The goal is getting a job, not shipping a product. Prefer the smallest change that serves
that goal; no speculative features or abstractions.

`docs/design.md` is the authoritative architecture — read the relevant section before
changing behavior, and update it when behavior changes.

## Layout
- `backend/` — FastAPI api + APScheduler worker, Python 3.12, package `jobsearch` in `src/`.
  - `api.py` (all routes) → `services/*` (business logic) → `models.py` (SQLAlchemy 2).
  - `ai/` — `AIProvider` protocol (`base.py`), `anthropic_provider.py`, `stub.py`,
    editable prompts (`prompts.py`), `posting_guard.py` (untrusted-text sanitizer).
  - `sources/` — self-registering job sources (`rss`, `remoteok`, `remotive`,
    `arbeitnow`, `freehire`). Add a source = new file + import in `sources/__init__.py`.
- `web/` — Next.js 15 App Router, TypeScript, no UI lib. All API calls via `web/lib/api.ts`
  (keep its interfaces in sync with `backend/src/jobsearch/schemas.py`).
- `k8s/base/` — Kustomize base consumed by the separate `k3s-lab` repo. No homelab values here.
- `docs/` — design + feature handovers (`ai-provider-swap.md`,
  `handover-application-generation.md`, `repo-comparison.md`, `extracted-prompts.md`).

## Commands (Windows; run from `backend/`)
A stale Python 3.7 is first on PATH — **never use bare `python`**. Always the venv:
- Tests: `.venv/Scripts/python.exe -m pytest -q`
- Lint:  `.venv/Scripts/python.exe -m ruff check src tests`
- Recreate venv: `py -3.12 -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev]"`
- Web: `cd web && npm run build` (type-checks); `npm run dev` for local UI.
- Full stack locally: `docker compose up --build` (api :8000, web :3000).
- Release: bump version in `api.py` (`FastAPI(version=...)`) and `k8s/base/kustomization.yaml`
  image tags, commit as `vX.Y.Z`, then `./build-push.sh vX.Y.Z`. Do not push/build unless asked.

## Database
- No Alembic migrations. `init_db.py` runs `create_all` (new tables only) on every start.
- New column on an existing table → add an idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` to `_COLUMN_TOPUPS`. Pre-existing rows get
  NULL, so schemas/UI must tolerate NULL for that column.
- Tests use in-memory SQLite (`tests/conftest.py`): JSONB degrades to JSON, and advisory
  locks no-op. Postgres-specific behavior (locks, concurrency) is NOT covered by tests.

## Processing model
- `analysis` and `application` rows are keyed by `(job_id, cv_id)`; status
  `pending → done | error` with `retry_count`. API endpoints enqueue (set `pending`) and
  return immediately; the worker's 5-second drain tick does the AI work. Follow this pattern
  for any new AI-backed feature — don't call the AI inside an HTTP request.
- A new CV = new active `cv_id`; old results remain but read as "outdated".
- Editing a job description marks its analysis `stale` (no auto-rescore).
- Application generation is opt-in per job — never run it over the backlog.

## AI layer contract
- Every prompt sent to a model lives in `ai/prompts.py` `SPECS` and is editable on
  `/prompts`. Never hardcode a prompt in a provider.
- Placeholders are a strict allowlist per prompt (see `SPECS[...].required_placeholders`).
  Literal braces in prompt text must be `{{` / `}}`.
- Users' saved prompt overrides in the DB shadow code defaults — when changing a default,
  tell the user to reset it on `/prompts` if they customized it.
- Keep `StubProvider` consistent with prompt scoring rules (it's the offline pipeline and
  the test backend). Scoring weights: technical 0.30 / experience 0.25 / seniority 0.15 /
  career alignment 0.30.
- All posting text goes through `posting_guard.sanitize()` before reaching a provider.
- New provider → see `docs/ai-provider-swap.md`.

## Non-negotiable rules
- **Never invent qualifications or experience.** Score/generate strictly from CV evidence
  and the explicit matching profile; a missing requirement is an honest gap. Preserve this
  in every prompt, stub, and AI-layer change.
- **LinkedIn is manual-only** (stored URL + pasted job URLs). Never auto-poll or scrape it.
- Sources: RSS + free public JSON APIs only, respect their terms (e.g. RemoteOK attribution).
- Secrets stay server-side; never commit `.env` (only `.env.example`).

## Conventions
- Python: ruff, line length 100, `from __future__ import annotations`, type hints,
  module docstrings explaining *why*. Comments explain intent and design reasons.
- Services take a `Session` as the first arg; API handlers stay thin.
- Tests are focused (pytest, fixtures in `tests/fixtures/`), no network, stub provider.

## Before saying a task is done
Run the venv test suite and `ruff` on changed files, and `npm run build` if `web/` changed.
A clean exit isn't proof — check the result against what was asked. Report pre-existing
lint/test failures rather than silently "fixing" unrelated code.
