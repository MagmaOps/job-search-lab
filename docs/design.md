# Design: Personal AI Job Search App

> Reference design for the homelab job-search application described in
> `docs/kiro_job_search_task.md`. This document captures the agreed architecture and
> decisions. It is a reference, not a task breakdown — implementation proceeds directly
> from here.

## 1. Decisions locked in

| Topic | Decision |
|-------|----------|
| AI provider | **Anthropic** (Claude). Configurable via env; key stays server-side. Not wired up yet — code behind an interface so it can run with a stub until the key is added. |
| Automated sources | **RSS feeds + free JSON APIs only** (compliant, no auth, no scraping). |
| LinkedIn | **Manual reference only.** Stored as a bookmarkable search URL + manual job-URL entry. The app never auto-polls LinkedIn (its guest/voyager endpoints violate ToS and the task's anti-bot rule). |
| Primary query | **DevOps Engineer, remote, EU-based candidates.** |
| Matching profile | **(c) Hybrid.** Auto-extract a baseline profile from the CV (skills, seniority, years), plus an editable profile where the user sets must-haves, nice-to-haves, dealbreakers, and minimum seniority. Jobs are validated against this profile. |
| CV handling | **Extracted data only.** Upload PDF/DOCX → extract text + derive matching profile → store in Postgres → **discard the file.** No file retention, no object/volume storage. |
| Auth | None. Private homelab network only; keep off the public internet. |
| Build artifact | **Docker image + Kustomize base** produced by this repo. |
| Deployment | **k3s** via the separate `k3s-lab` repo (overlays, patches, secrets, ingress). |
| Database | **PostgreSQL via CloudNativePG (CNPG)** for automatic HA/failover. Operator + `Cluster` CR live in `k3s-lab`; this app only consumes the DB. |

### LinkedIn access — the limitation, stated plainly
LinkedIn removed public job RSS years ago and has no individual-accessible job API.
The only automated paths are the official partner API (not available to individuals) or
scraping the `jobs-guest` endpoints (violates the User Agreement and trips anti-bot
protection). Per the task's "respect source terms / do not bypass anti-bot" requirement,
the app treats LinkedIn as a **manual** source: it stores a search URL you open yourself,
and you paste interesting job URLs into the app for analysis.

### Confirmed LinkedIn search parameters (for the stored reference URL)
- `keywords=DevOps Engineer`
- `f_WT=2` → remote (`1`=on-site, `2`=remote, `3`=hybrid)
- `geoId=91000000` → European Union (`92000000` = Worldwide). *Unofficial values — verify once in-browser; LinkedIn geoIds drift.*
- `f_TPR=r604800` → posted in last 7 days (`r86400`=24h)
- `sortBy=DD` → newest first

Primary (EU-based remote):
```
https://www.linkedin.com/jobs/search/?keywords=DevOps%20Engineer&location=European%20Union&geoId=91000000&f_WT=2&f_TPR=r604800&sortBy=DD
```

### Confirmed automated sources
| Source | Endpoint | Notes |
|--------|----------|-------|
| We Work Remotely (DevOps) | `https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss` | RSS |
| RemoteOK | `https://remoteok.com/api?tag=devops` | JSON; needs `User-Agent` header; first array item is a legal notice; attribution required |
| Remotive | `https://remotive.com/api/remote-jobs?category=devops` | JSON |
| Arbeitnow | `https://www.arbeitnow.com/api/job-board-api` | JSON; EU-friendly board |

## 2. Architecture

Simple, maintainable stack for a homelab k3s cluster. Avoid extra services.

```
            ┌──────────────────────── k3s cluster (via k3s-lab) ────────────────────────┐
            │                                                                            │
 Browser ──►│  Ingress ──► web (Next.js, Deployment, replicas≥2)                         │
            │                         │                                                  │
            │                         ▼                                                  │
            │              api (FastAPI, Deployment, replicas≥2) ──┐                     │
            │                                                      │                     │
            │   worker (Deployment, leader-elected single active) ─┤                     │
            │     - scheduled collection (a few times/day)         │                     │
            │     - AI analysis queue                              ▼                     │
            │                                          CNPG Postgres Cluster             │
            │                                          (primary + replicas, auto         │
            │                                           failover, -rw / -ro Services)     │
            └────────────────────────────────────────────────────────────────────────────┘

   app image + Kustomize base  ──►  consumed & patched by  ──►  k3s-lab repo
```

Services (all from one Docker image, different entrypoints/commands):
- **web** — Next.js dashboard, CV upload, query & matching-profile management. Talks to the API only.
- **api** — FastAPI. REST endpoints, CV text extraction + profile derivation, business logic, DB access.
- **worker** — scheduled collection + AI analysis queue. **Single active instance via
  leader election** (k8s `Lease`) so multiple replicas don't double-collect; a standby
  replica takes over if the leader's node dies.
- **db** — PostgreSQL provided by **CNPG** (not in this repo's base beyond a reference).

No message broker (no Redis/Celery) — the worker polls a DB-backed queue. Enough for
homelab volume; can swap to a broker later.

### High availability (goal: nodes go down often)
- **Stateless app (web/api)**: `replicas ≥ 2`, pod anti-affinity to spread across nodes,
  PodDisruptionBudget. Node loss → Deployment reschedules onto a surviving node; the other
  replica keeps serving meanwhile.
- **Worker**: 2 replicas but only the leader runs the scheduler/collector; failover is
  automatic via the k8s Lease.
- **Data**: **CloudNativePG** runs a primary + synchronous replica(s) across nodes with
  streaming replication and **automatic failover** (promotes a replica when the primary's
  node dies). The app connects to the CNPG `-rw` Service, which always points at the
  current primary. Because the only stateful thing is Postgres (CV files are discarded),
  CNPG replication makes the whole data layer HA — no shared volume needed.

### Source abstraction (modular, task requirement 3)
```python
class JobSource(Protocol):
    name: str
    def fetch(self, query: SearchQuery) -> list[RawJob]: ...
```
Implementations: `RssSource`, `RemoteOkSource`, `RemotiveSource`, `ArbeitnowSource`,
`ManualUrlSource` (LinkedIn pastes). A registry maps `source` name → implementation so new
sources are added without touching the scheduler.

## 3. Data model

```
cv
  id, source_filename, extracted_text,    -- file itself is NOT stored
  derived_profile (jsonb),                -- auto-extracted skills/seniority/years
  uploaded_at, is_active

matching_profile                          -- editable, (c) hybrid matching
  id, cv_id,
  must_have_skills (jsonb), nice_to_have_skills (jsonb),
  dealbreakers (jsonb), min_seniority, notes,
  updated_at

search_query
  id, name, enabled, keywords, work_type, location, source,       -- e.g. 'remoteok'
  source_config (jsonb),  -- feed url / tag / linkedin url / schedule overrides
  reference_url,          -- the manual LinkedIn bookmark
  created_at, updated_at

job
  id, source, source_job_id (nullable), url, normalized_url,
  fingerprint,            -- fallback dedup: hash(source,company,title,location)
  title, company, location, description, language,
  discovered_at, content_hash,   -- to detect "changed" jobs
  status,                 -- new | saved | dismissed | applied | interview
  created_at, updated_at
  UNIQUE (normalized_url)
  UNIQUE (source, source_job_id)        -- partial, where source_job_id not null
  UNIQUE (fingerprint)

analysis
  id, job_id, cv_id,      -- tie analysis to the CV version used
  processing_status,      -- pending | done | error
  error_message, retry_count,
  detected_language, translated_summary,
  match_score, explanation, matching_skills (jsonb), missing_requirements (jsonb),
  dimension_scores (jsonb),   -- per-dimension breakdown behind the score
  learning_gaps (jsonb),      -- "gaps to close": [{skill, level: basic|average, why}]
  stale (bool),               -- description edited after this score → show "stale", no auto-rescore
  model, created_at
  UNIQUE (job_id, cv_id)  -- re-analyze when CV changes = new row

application                -- tailored CV + cover letter per job (see §5a)
  id, job_id, cv_id,       -- same (job, cv) caching key as analysis
  processing_status,       -- pending | done | error
  error_message, retry_count,
  cover_letter_md,         -- tailored cover letter (Markdown), user-editable
  cv_summary_md,           -- tailored profile statement + reframed bullets (Markdown)
  reviewer_notes,          -- the drafter→reviewer critique, for transparency
  model, created_at, updated_at
  UNIQUE (job_id, cv_id)   -- one current application per job per CV version
```

### Deduplication (task requirement 5)
1. **Normalize URL** — lowercase host, strip tracking params (`utm_*`, `ref`, fragments,
   trailing slash). Store as `normalized_url` with a unique constraint.
2. **Source job ID** — when the source gives a stable ID, `UNIQUE (source, source_job_id)`.
3. **Fallback fingerprint** — `sha256(source | company | title | location)` when no URL/ID.
4. DB-level `UNIQUE` constraints do the enforcement; inserts use upsert
   (`ON CONFLICT DO NOTHING / DO UPDATE` on content change).

### Avoiding repeated AI work (task requirement 5 & 6)
- `job.content_hash` captures the normalized description. On re-collection, unchanged hash
  → skip analysis.
- `analysis` keyed by `(job_id, cv_id)`. Same job + same CV → reuse cached result.
- **CV changes** → new `cv` row becomes active → existing jobs become eligible for a fresh
  `(job_id, new_cv_id)` analysis (queued, not forced, unless manually requested).
- Manual re-analysis endpoint forces a new run regardless of cache.
- Failures stored with `processing_status=error`, `error_message`, `retry_count` for retry.

## 4. CV ingestion & matching profile (requirement 2 & 6, option c)
- Upload PDF/DOCX → extract text (`pypdf` / `python-docx`) → **discard the file**.
- Derive a baseline profile from the text via the AI provider: skills, seniority, years.
- Store `cv.extracted_text` + `cv.derived_profile`; create/seed an editable
  `matching_profile` the user can override (must-haves, nice-to-haves, dealbreakers,
  min seniority).
- Job validation uses the **effective profile** = derived baseline merged with the user's
  explicit overrides.

## 5. AI matching & translation (requirement 6)
- `AIProvider` interface; `AnthropicProvider` implementation + `StubProvider` for local
  dev before the key exists.
- Pipeline per job: detect language → (if non-English) translate relevant fields →
  validate the description against the **effective matching profile** → produce
  `match_score (0-100)`, `explanation`, `matching_skills`, `missing_requirements`.
- Prompt guardrail: **never invent qualifications**; score strictly from CV evidence and
  the explicit profile.
- Store original + translated summary; dashboard shows both.
- All results persisted to avoid repeat calls.

## 5a. Application generation (the apply half of the funnel)
Finding and scoring jobs only pays off if you then apply well. This stage turns a scored
job into a **sendable application**: a tailored cover letter + CV summary, grounded strictly
in the active CV and matching profile.

- **Contract**: `AIProvider.generate_application(...)` returns an `ApplicationDraft`
  (`cover_letter_md`, `cv_summary_md`, `reviewer_notes`, `model`). Both providers implement
  it; the `StubProvider` is deterministic and offline (assembles from profile facts,
  invents nothing) so the pipeline and tests run without a key.
- **Two-pass drafter → reviewer**: the Anthropic provider drafts, runs a reviewer critique
  (a mandatory factual-grounding audit + missed-keyword/framing/tone feedback), then revises
  once. The critique is persisted as `reviewer_notes`. The stub produces a grounding-focused
  note deterministically.
- **Editable prompts**: three new prompts — `application` (drafter), `application_review`
  (reviewer), and `application_revise` (applies the critique) — live in `ai/prompts.py`
  `SPECS`, overridable and validated on the `/prompts` page exactly like `profile`/`analyze`.
  Every prompt the flow sends to the model is user-editable; none are hardcoded.
- **Writing-style discipline** (adapted from `ai-job-search`'s methodology): the drafter and
  reviewer prompts enforce no em-dashes / no clichés / no apologetic hedging, first-person
  active voice, forward-looking cover-letter framing (tasks you'll solve, not a CV recap),
  measurable results, honest in-progress qualifications, and the "interview-backtrack test"
  (reframe emphasis, never substance). PDF/LaTeX layout, ATS text-layer checks, and company
  web research from that repo are deliberately out of scope for this stage (see the handover
  §1a table).
- **Same pipeline shape as analysis**: queued (`pending`) per `(job_id, cv_id)`, drained by
  the worker, advisory-locked, posting text sanitized via `posting_guard` first. A CV change
  invalidates old applications; "Regenerate" resets the row to `pending`. Generation is
  opt-in per job (the user clicks **Generate application**), never run over the whole backlog.
- **Never invent** (design §... the non-negotiable rule): every claim traces to the CV +
  effective profile. A missing requirement is stated as an honest gap, never fabricated —
  enforced in both prompts, the revision step, and the stub.
- **Markdown first**: output is Markdown (`cover_letter_md` + `cv_summary_md`), editable in
  the dashboard. LaTeX/PDF compilation is a deliberately deferred, separate stage.

## 6. Web dashboard (requirement 7)
Pages:
- **Dashboard** — jobs ranked by `match_score`. Columns: title, company, location,
  language, score, summary, discovered_at, original link. Filters: score, location,
  company, language, status. Status actions: saved / dismissed / applied / interview.
  Header shows last search time + recent errors. The expanded row also generates a
  tailored application (cover letter + CV summary) for the job — edit, save, regenerate.
- **CV** — upload/replace (PDF/DOCX), shows active CV extraction status + derived profile,
  and lets the user edit the matching profile (must-haves / dealbreakers / etc.).
- **Queries** — list/add/edit/enable/disable/delete; includes the predefined DevOps query.

## 7. API surface (FastAPI)
```
GET    /jobs?min_score&location&company&language&status&sort
PATCH  /jobs/{id}        (status)
POST   /jobs/manual      (paste a URL → fetch metadata → queue analysis)
POST   /jobs/{id}/reanalyze
GET    /jobs/{id}/application    (current tailored application for the active CV)
POST   /jobs/{id}/application    (queue/regenerate; worker drafts → reviews → revises)
PATCH  /jobs/{id}/application    (save user edits to the cover letter / CV summary)
GET    /queries   POST /queries   PATCH /queries/{id}   DELETE /queries/{id}
POST   /queries/{id}/run   (manual trigger)
GET    /cv        POST /cv (upload → extract → discard file)
GET    /profile   PATCH /profile   (editable matching profile)
GET    /status    (last run, errors, counts)
GET    /healthz   /readyz          (k8s probes)
```

## 8. Configuration (env, server-side)
```
DATABASE_URL=postgresql://...        # points at CNPG -rw Service
ANTHROPIC_API_KEY=                   # empty → StubProvider
AI_PROVIDER=anthropic
AI_MODEL=claude-...
COLLECT_SCHEDULE=0 */6 * * *         # configurable; a few times/day
LEADER_ELECTION=true                 # worker HA
```
Secrets come from k8s Secrets (CNPG-generated DB creds; Anthropic key sealed in `k3s-lab`).
The Kustomize base references Secret **names only** — no real values in this repo.
`.env.example` documents keys for local dev.

## 9. Packaging & deployment (requirement 1 & 9)
- **Dockerfile** builds one image serving api/worker (Python) and a separate web image
  (Next.js) — or a single multi-stage image with role via command. (Decide at build.)
- **Kustomize base** (`k8s/base/`): Deployments (web, api, worker), Services, Ingress,
  ConfigMap, HPA/PDB, probes, and a reference to the DB Secret + CNPG `-rw` Service.
  Exposes patch points (image tags, replicas, resources, env, ingress host, storage class)
  with **no hardcoded homelab values**.
- **`k3s-lab` owns**: CNPG operator + `Cluster` CR, overlays/patches, sealed secrets,
  ingress host/TLS, node specifics.
- **README**: build the image, how `k3s-lab` consumes the base, configuration, manual run,
  CNPG backup/restore, how to add a source, LinkedIn limitation note.
- Seed migration inserts the predefined DevOps query (RemoteOK/Remotive/WWR auto sources +
  LinkedIn reference URL).

## 10. Testing (requirement 8)
Focused tests only (not auto-added beyond the task's ask):
- URL normalization + dedup (all three strategies).
- Content-hash "unchanged → skip" logic.
- Analysis cache reuse and retry-on-error.
- Source parsers against sample fixtures.
- Worker leader-election single-active behavior.
Use **sample job fixtures** to validate end-to-end before hitting live feeds.

## 11. Build order (direct, no task tracking)
1. Repo scaffold + Dockerfile(s) + local dev compose (dev only) + Postgres for local.
2. DB schema + migrations + seed query.
3. FastAPI core + source abstraction + RSS/API sources (with fixtures).
4. Dedup + content-hash + upsert.
5. CV upload + text extraction + derived/editable matching profile.
6. AI provider interface + StubProvider (+ Anthropic behind it).
7. Worker: scheduler + analysis queue + leader election.
8. Next.js dashboard, CV/profile, queries pages.
9. Kustomize base (Deployments/Services/Ingress/ConfigMap/PDB/probes, CNPG consumption).
10. Tests + README.
