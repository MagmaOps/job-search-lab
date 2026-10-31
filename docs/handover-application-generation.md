# Handover: Application Generation (the interview-landing stage)

> **For the next session.** Read this top to bottom before writing code. It defines the one
> big feature our app is missing, grounds it in the existing codebase, and gives a staged
> plan. Companion docs: `docs/repo-comparison.md` (why this matters), `docs/design.md` (our
> architecture), `docs/extracted-prompts.md` (the methodology to adapt), and the read-only
> reference clone at `ai-job-search/`.

---

## 1. The gap, in one sentence

Our app finds, dedupes, scores, and ranks DevOps jobs — but it **stops at the match score**.
The `ai-job-search` repo's strongest feature, and the half of the funnel that actually lands
interviews, is **application generation**: turning a scored job + the CV into a *tailored CV
and cover letter*, critiqued by a reviewer pass, grounded strictly in real profile facts.

`repo-comparison.md` scored them 3 vs our 0 on "Tailored CV + cover letter per job" and
flagged it as our single biggest gap. This handover is about closing it.

**Goal reminder:** the point is to get the user a DevOps job, not to build a product. Favor
the smallest thing that produces a sendable application. Do not gold-plate.

---

## 1a. Scope & sequencing rationale (read before you get ambitious)

This handover implements **only the two highest-value items** from the "Unique to
ai-job-search" list in `repo-comparison.md`: the **tailored CV + cover letter** and the
**drafter→reviewer loop**. That is deliberate. Do not try to port their whole feature set —
it works against the goal (get a DevOps job fast), not toward it.

Here is every "Unique to ai-job-search" feature and the decision for each:

| Feature | Decision | Why |
|---|---|---|
| Tailored CV + cover letter per job | **BUILD NOW** | The one gap that changes outcomes: turns "50 ranked jobs" into "a sendable application". All the upstream collect/dedup/rank work only pays off if you then apply well. |
| Drafter → reviewer loop | **BUILD NOW** | Cheap quality multiplier on the above; catches missed keywords, weak framing, and ungrounded claims. Part of the same stage. |
| Prompt-injection hardening | **DONE** | Already shipped as `ai/posting_guard.py`; just reuse it. |
| PDF compile + layout verification | **LATER (next)** | You'll need a real PDF to submit — but prove the *content* is good in Markdown first. Add when you actually need to send a PDF, as its own task. |
| Interview prep + mock (`/interview`) | **LATER** | Genuinely useful, but worthless until applications land interviews. Correctly sequenced *after* this stage. Don't build speculatively. |
| Outcome tracking + follow-ups | **LATER / maybe never** | A spreadsheet covers it for one person's search. Only if the search drags on. |
| ATS text-layer check | **PROBABLY NEVER** | Matters for big-corp ATS funnels; polish for targeted DevOps applications. Revisit only if auto-rejections appear. |
| Salary benchmarking | **SKIP** | We already have manual salary edit + the eligibility signal. Theirs needs a salary dataset we don't have. |
| Upskill / gap analysis | **SKIP** | Career-planning feature, orthogonal to landing *this* job. |

**Sequencing rule for this session:** ship Stages 1-4 (content → storage → API → UI), then
**stop and have the user generate a few real applications** and judge the output quality
*before* investing in PDF compilation. Only after the content is proven good does PDF become
the next worthwhile investment. Interview prep comes only once an application lands an
interview. Resist implementing anything in the LATER/SKIP rows during this session.

The framing to keep in mind (from `repo-comparison.md`): our app wins the *finding* half of
the funnel; theirs wins the *applying* half. We only need to close the applying half **enough
to send strong applications** — that is the tailored-CV + reviewer loop, nothing more.

---

## 2. What "done" looks like (acceptance)

A user can, from a scored job in the dashboard:
1. Click **"Generate application"** on a job.
2. The backend produces a **tailored cover letter** (and a tailored CV summary/bullets)
   targeted at that posting, using only facts in the active CV + matching profile.
3. A **reviewer pass** critiques the draft (missed keywords, weak framing, tone, and a
   factual-grounding check) and the draft is revised once.
4. The result is **stored** (per job + CV version, like `analysis`) and shown in the UI,
   editable by the user, with the ability to regenerate.
5. **Never invents** skills/experience — a gap is stated honestly, never fabricated.

Explicitly **out of scope** for the first cut (note but don't build unless asked):
- LaTeX/PDF compilation + the layout/ATS verification loop (their `/apply` steps 5-7).
  Start with Markdown/plain-text output; PDF is a later, separate task.
- Interview prep (`/interview`) and outcome tracking (`/outcome`) — future stages.
- Multi-document ingestion (LinkedIn/diploma cross-referencing). We decided to skip it.

---

## 3. Where this fits in the existing code

Backend package: `backend/src/jobsearch/`. Study these before changing anything.

| Concern | File(s) | Note |
|---|---|---|
| AI provider contract | `ai/base.py` | `AIProvider` protocol, `ProfileExtraction`, `MatchResult`, `DimensionScore`. Add the new method here. |
| Anthropic impl | `ai/anthropic_provider.py` | `_complete_json`, token budgets. The JSON-truncation fix (`max_tokens`) lives here — the application prompt will be long, budget accordingly. |
| Stub impl | `ai/stub.py` | Offline, deterministic, no key. **Must** get a stub implementation of the new method so the pipeline works without tokens and tests stay free. |
| Editable prompts | `ai/prompts.py` | `PROFILE`, `ANALYZE` prompts + the strict placeholder validator (`validate`/`render`). New prompts go here with their own required-placeholder set. |
| Prompt persistence/UI | `services/prompt_service.py`, `models.PromptTemplate`, `/prompts` API, `web/app/prompts/` | New prompts become editable in the UI for free if registered in `SPECS`. |
| Analysis pipeline (the pattern to mirror) | `services/analysis_service.py` | `(job_id, cv_id)` caching, `pending`→worker-drain queue, advisory lock, posting_guard sanitize. **Application generation should follow this exact shape.** |
| CV + effective profile | `services/cv_service.py` | `get_active_cv`, `effective_profile(cv)` — the fact source for grounding. |
| Posting trust boundary | `ai/posting_guard.py` | Sanitize the job description before it reaches the model. Reuse it. |
| Data model | `models.py` | Add the new table here (see §5). Uses `create_all` + `_COLUMN_TOPUPS` in `init_db.py` — NO Alembic. |
| API | `api.py` | Root-level routes (ingress strips `/api`). Add generate/get/regenerate endpoints. |
| Web | `web/app/page.tsx`, `web/lib/api.ts` | Dashboard expanded-row is where the button + output live. |

**The methodology to adapt** is already extracted in `docs/extracted-prompts.md`:
- §1b CV tailoring prompt (profile statement, relevance-weighted bullets, honest gaps).
- §3c reviewer critique (Part A structured edits + Part B narrative, grounding audit).
- §4 the non-negotiable never-invent rule.
Reference source in the clone: `ai-job-search/.claude/commands/apply.md` (steps 1-4) and
`.claude/agents/application-reviewer.md`.

---

## 4. Design decisions already made (respect these)

- **Reuse the analysis pattern, don't invent a new one.** Generation is queued (`pending`),
  the worker drains it, the UI polls + shows a spinner — identical to re-analyze. This is
  why closing the browser doesn't lose work. See `analysis_service.enqueue_job` /
  `analyze_pending` and the worker's `_drain_analysis_queue` tick.
- **Cache by `(job_id, cv_id)`** so a CV change invalidates old applications, same as
  `analysis`. Regeneration is a manual override that resets to `pending`.
- **Two-pass drafter→reviewer in one provider method** is fine (cheaper than two agents).
  The reviewer critique and the revision can be one orchestrated call sequence in the
  service, or a single prompt that drafts-then-self-critiques. Prefer the explicit two-call
  version for quality, but keep it one service function.
  - IMPLEMENTED as three calls (draft → review → revise), each driven by its own editable
    prompt (`application`, `application_review`, `application_revise`). Every prompt the
    flow sends is on the `/prompts` page — nothing is hardcoded in the provider.
- **Output format: Markdown first.** `cover_letter_md` + `cv_tailored_md` (or structured
  sections). No LaTeX yet. This keeps it testable and useful immediately.
- **Grounding is mandatory.** Every claim traces to `cv.extracted_text` +
  `effective_profile`. The prompt must forbid invention; the stub must only emit facts it
  can see in the profile. This is the same guardrail already in the `ANALYZE` prompt.
- **Prompts are editable.** Register the new prompt(s) in `ai/prompts.py` `SPECS` so they
  appear on the `/prompts` page and are overridable/validated like the existing two.
- **No tests with real tokens.** Tests run on the stub only (per project rule). Verify with
  `backend/.venv/Scripts/python.exe -m pytest -q`.

---

## 5. Suggested data model

Mirror `analysis`. Add to `models.py`:

```
application
  id, job_id (fk), cv_id (fk),
  processing_status        -- pending | done | error   (reuse ProcessingStatus enum)
  error_message, retry_count,
  cover_letter_md,         -- tailored cover letter (Markdown)
  cv_summary_md,           -- tailored profile statement + reframed bullets
  reviewer_notes,          -- the critique the reviewer produced (for transparency)
  model, created_at, updated_at
  UNIQUE (job_id, cv_id)   -- one current application per job per CV version
```

Add to `init_db.py` `_COLUMN_TOPUPS` only if you later add columns to an existing table;
a brand-new table is created by `create_all` automatically.

---

## 6. Staged implementation plan

Do these in order; each stage is independently verifiable on the stub.

**Stage 1 — AI contract + prompt + stub (no API/UI yet).**
- Add `generate_application(...)` to the `AIProvider` protocol in `ai/base.py`, returning an
  `ApplicationDraft` dataclass (cover_letter_md, cv_summary_md, reviewer_notes, model).
- Add `DEFAULT_APPLICATION_PROMPT` (+ reviewer prompt if two-pass) to `ai/prompts.py`,
  register in `SPECS` with required placeholders (e.g. `{profile}`, `{cv}`, `{title}`,
  `{description}`). Escape literal JSON braces as `{{ }}` (the validator rejects stray
  placeholders — see the project steering note).
- Implement it in `stub.py` (deterministic: assemble a plausible letter from profile facts
  + matched skills; invent nothing) and in `anthropic_provider.py` (adapt extracted-prompts
  §1b + §3c; raise `max_tokens` — these responses are long).
- Verify: a small unit test on the stub producing a draft from a fake CV+job.

**Stage 2 — persistence + service (mirror analysis_service).**
- `models.Application` + wire into `init_db`.
- `services/application_service.py`: `enqueue_application(job_id)`, and a
  `generate_pending(limit)` the worker calls — sanitize the posting via `posting_guard`,
  load `effective_profile`, call the provider, store, cache by `(job_id, cv_id)`, handle
  errors/retries, advisory-lock like analysis.
- Add a worker tick (or extend the existing analysis drain) to process generation jobs.
- Verify: service test on the stub — enqueue → drain → row is `done` with content.

**Stage 3 — API.**
- `POST /jobs/{id}/application` (enqueue/regenerate), `GET /jobs/{id}/application`
  (fetch current). Root-level routes (ingress strips `/api`).
- Verify: FastAPI TestClient against the stub.

**Stage 4 — Web.**
- Dashboard expanded row: a **Generate application** button (spinner + poll, reuse the
  `pending` pattern already there), render the cover letter + CV summary, allow edit + a
  Regenerate button. Add the types/calls to `web/lib/api.ts`.
- Verify: `cd web && npx tsc --noEmit` and `npm run build`.

**Stage 5 — editable prompts surface + docs.**
- Confirm the new prompt(s) show on `/prompts` and round-trip.
- Update `docs/design.md` (add an Application Generation section) and the steering file.

---

## 7. Gotchas carried over from this project (save yourself the pain)

- **Python:** always use `backend/.venv/Scripts/python.exe` — system `python` is 3.7 on PATH.
- **No Alembic:** schema via `create_all`; add columns to existing tables through the
  idempotent `_COLUMN_TOPUPS` `ALTER ... ADD COLUMN IF NOT EXISTS` in `init_db.py`.
- **Prompt validator:** literal `{`/`}` in a prompt MUST be `{{`/`}}` or it's rejected as an
  unknown placeholder.
- **JSON truncation:** long AI responses hit `max_tokens` and fail JSON parsing — budget
  generously and keep the "raise max_tokens" error hint.
- **Keep the stub faithful:** when the prompt's rules change, mirror them in the stub so the
  offline pipeline behaves the same (and tests stay token-free).
- **Posting text is untrusted:** always run `posting_guard.sanitize` before the model.
- **Deployment is already done** — don't touch `k8s/` or k3s-lab for this feature. A new
  app version just needs `./build-push.sh vX.Y.Z` then a tag bump in the k3s-lab workload
  kustomization (blue-green rollout handles the rest). Only relevant once the feature ships.

---

## 8. First steps for the new session

1. Read `docs/repo-comparison.md` §5, `docs/extracted-prompts.md` §1b/§3c/§4, and
   `ai-job-search/.claude/commands/apply.md` steps 1-4.
2. Read `backend/src/jobsearch/services/analysis_service.py` and `ai/prompts.py` in full —
   you are cloning that shape.
3. Start Stage 1. Confirm the stub produces a grounded draft before touching the DB/API/UI.
4. Keep each stage green on the venv test suite before moving on. No real-token tests.
