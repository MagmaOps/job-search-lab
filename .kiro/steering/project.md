# Job Search Lab — project conventions

Personal AI job-search app for landing a **remote EU DevOps role**. The goal is getting a
job, not shipping a product for others. Prefer the smallest change that serves that goal;
don't add product features or abstractions beyond what a task needs.

## Layout
- `backend/` — FastAPI API + worker, Python 3.12, package `jobsearch` under `src/`.
- `web/` — Next.js dashboard (dashboard, CV, queries, prompts pages).
- `k8s/base/` — Kustomize base (consumed by a separate `k3s-lab` repo). `build-push.sh`
  (repo root) builds + pushes the two Docker Hub images.
- `docs/` — `design.md` (architecture, authoritative), `kiro_job_search_task.md` (the task),
  plus analyses: `repo-comparison.md`, `extracted-prompts.md`.
- `ai-job-search/` — a **third-party reference clone** (`github.com/ai-job-search-dev/...`),
  audited safe. Read it for ideas; never run it as a dependency of our app.

## Python environment (important)
- The project requires **Python 3.12**. A stale system Python 3.7 is first on the bash
  PATH, so bare `python` resolves to 3.7 and has no deps. **Always use the venv.**
- Run everything through `backend/.venv`:
  - Tests: `backend/.venv/Scripts/python.exe -m pytest -q`
  - Lint: `backend/.venv/Scripts/python.exe -m ruff check src tests`
- If the venv is missing, recreate it: `py -3.12 -m venv .venv` then
  `.venv/Scripts/python.exe -m pip install -e ".[dev]"` (run from `backend/`).

## Database & schema changes
- Schema is created with `Base.metadata.create_all` in `init_db.py` (no Alembic migration
  files, despite alembic being a dependency). `create_all` creates missing tables but
  **never alters an existing table**.
- To add a column to an existing table, add an idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` to `_COLUMN_TOPUPS` in `init_db.py`. That
  list runs on every startup under an advisory lock — keep every statement idempotent.
- Tests use in-memory SQLite (`conftest.py`); `JSONB` degrades to JSON there, which is fine.
  Production is Postgres via CloudNativePG.

## AI layer contract
- Two editable prompts live in `ai/prompts.py`: `PROFILE` and `ANALYZE`. They are
  user-overridable via the API/UI and validated against a strict placeholder allowlist.
  - `profile` allows only `{cv}`.
  - `analyze` allows only `{profile}`, `{cv}`, `{title}`, `{description}`.
  - Literal braces in a prompt (e.g. JSON examples) MUST be escaped as `{{` / `}}` or the
    validator rejects them as unknown placeholders.
- Two providers behind `ai/base.py`'s `AIProvider` protocol: `StubProvider` (offline, no
  key, deterministic keyword logic) and `AnthropicProvider` (when `ANTHROPIC_API_KEY` set).
  **Keep the stub behavior consistent with the prompt rules** — when you change scoring
  rules in the prompt, mirror them in the stub so the offline pipeline stays faithful.
- `analyze` output is persisted per `(job_id, cv_id)` in the `analysis` table and includes
  a per-dimension `dimension_scores` breakdown (technical / experience / seniority /
  career alignment, with weights 0.30/0.25/0.15/0.30 and a one-line reason each).
- Untrusted job text passes through `ai/posting_guard.py` (strips hidden/invisible content,
  flags instruction-shaped lines) **before** it reaches the model. Always sanitize posting
  text before sending it to a provider.

## The one non-negotiable rule
**Never invent qualifications or experience.** Score strictly from CV evidence and the
explicit matching profile. A missing requirement is an honest gap, never assumed met. This
rule is in `design.md` §5 and baked into both prompts and the stub — preserve it in any
change to the AI layer.

## LinkedIn
Manual reference only — stored search URL + manual job-URL paste. Never auto-poll LinkedIn
(ToS + anti-bot). This is a locked design decision.

## Before saying a task is done
Run the venv test suite and `ruff` on changed files. A clean exit is not proof — check the
actual result against what was asked. Note any pre-existing lint/test issues rather than
silently "fixing" unrelated code.
