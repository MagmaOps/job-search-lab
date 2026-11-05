# Swapping or adding an AI provider

> How to move off Anthropic (or run a second provider) with minimal churn. The app was
> built behind a provider interface, so this is a contained change — not a refactor.
> Read `design.md` §5 / §5a first for what the provider is expected to produce.

## TL;DR

The whole app talks to the model through **one interface** (`AIProvider` in
`backend/src/jobsearch/ai/base.py`). Services, API, DB, prompts, worker, and UI never
reference Anthropic directly — they call `get_provider()` and use the protocol methods. So a
new provider is essentially **one new file** implementing three methods, plus a few lines of
config wiring. Everything else is reuse.

## What is already provider-agnostic (no work)

- The `AIProvider` protocol and all result dataclasses: `ProfileExtraction`, `MatchResult`,
  `DimensionScore`, `LearningGap`, `ApplicationDraft` (`ai/base.py`).
- Every prompt and the validator (`ai/prompts.py`) — plain text with placeholders, vendor
  neutral, user-editable on `/prompts`.
- The `StubProvider` (`ai/stub.py`) — proves the app runs with *no* provider; keep it as the
  keyless/offline/default and the token-free test backend.
- The trust boundary (`posting_guard`), `(job_id, cv_id)` caching, the queue/worker, the DB
  schema, the API, and the UI.

## The three things that currently assume Anthropic

These are the only friction points. Loosen them when you add the second provider — not
before (don't abstract speculatively).

1. **Config** (`ai/config.py`). `ai_enabled` is hardcoded:
   ```python
   return bool(self.anthropic_api_key) and self.ai_provider == "anthropic"
   ```
   Even though `ai_provider` exists as a setting, only `"anthropic"` is recognized. Needs a
   generic key (or per-provider keys) and a `get_provider()` that branches on `ai_provider`.

2. **The robust-JSON helper lives inside `AnthropicProvider`** (`ai/anthropic_provider.py`):
   `_complete_json` (newline-salvage + truncation message), plus `_escape_control_chars_in_
   strings`, `_parse_dimensions`, `_parse_learning_gaps`, `_norm_eligibility`,
   `_format_review_notes`. These are genuinely vendor-neutral (any JSON-returning model hits
   the same raw-newline problem). Lift them into a shared module so a new provider reuses
   them instead of re-solving the bug.

3. **Stub user-facing strings and the model default** mention Anthropic/Claude
   (`ai/stub.py` notes; `config.ai_model = "claude-haiku-5-5"`). Cosmetic.

## Step-by-step

### Step 1 — Extract the shared JSON helpers (prep, no behavior change)

Move from `ai/anthropic_provider.py` into a new `ai/json_utils.py`:
`_escape_control_chars_in_strings`, `_parse_dimensions`, `_parse_learning_gaps`,
`_norm_eligibility`, `_format_review_notes`, and a standalone `complete_json(client_call,
max_tokens)` that wraps the "call → strip fences → json.loads → salvage newlines → raise
actionable error on truncation" logic. Import them back into `AnthropicProvider` so its
behavior is unchanged. Add a unit test that the salvage still handles raw newlines (one
already exists in `tests/test_application.py` — point it at the new module).

This step alone is safe to do any time and makes the eventual swap a true one-file job.

### Step 2 — Generalize config

In `ai/config.py`:
- Add the new key(s), e.g. `openai_api_key: str = ""` (or a single `ai_api_key`).
- Replace the hardcoded `ai_enabled` with provider-aware logic, e.g. a small map from
  `ai_provider` → required key. Keep "no key → stub" as the fallback.
- Add the new provider to `.env.example` and the `k8s/base` ConfigMap/Secret references
  (the real key is sealed in `k3s-lab`, like `ANTHROPIC_API_KEY`).

### Step 3 — Write the provider (the only genuinely new code)

Create `ai/<vendor>_provider.py` implementing the `AIProvider` protocol:

```python
class VendorProvider:
    model: str

    def __init__(self, settings: Settings) -> None:
        from vendor_sdk import Client            # import lazily (as AnthropicProvider does)
        self._client = Client(api_key=settings.<vendor>_api_key)
        self.model = settings.ai_model

    def extract_profile(self, cv_text, template=None) -> ProfileExtraction: ...
    def analyze_job(self, *, job_title, job_description, job_language, cv_text,
                    effective_profile, template=None) -> MatchResult: ...
    def generate_application(self, *, job_title, job_description, cv_text,
                             effective_profile, draft_template=None,
                             review_template=None, revise_template=None) -> ApplicationDraft: ...
```

The bulk of each method is: `prompts.render(...)` the (already-editable) template → call the
SDK → `complete_json(...)` → map the dict into the dataclass. Mirror `AnthropicProvider`
closely — the prompt rendering, token budgets (draft/revise large, review mid), and
result-parsing are all the same shape.

**Must-keep behaviors** (the contract the rest of the app relies on):
- Never invent qualifications — the prompts already enforce it; don't weaken them.
- `analyze_job` must return the four `dimension_scores`, `learning_gaps`, eligibility fields,
  and a laconic `explanation`.
- `generate_application` returns all three Markdown docs + `reviewer_notes`, via the
  draft → review → revise sequence, and must survive long multi-line Markdown in JSON
  strings (use the shared `complete_json`).

### Step 4 — Wire the factory

In `ai/__init__.py` `get_provider()`, branch on `settings.ai_provider`:

```python
if settings.ai_enabled:
    if settings.ai_provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(settings)
    if settings.ai_provider == "<vendor>":
        from .<vendor>_provider import VendorProvider
        return VendorProvider(settings)
return StubProvider()
```

Keep imports lazy so one vendor's SDK is never required to run the other (or the stub).

### Step 5 — Verify

- `backend/.venv/Scripts/python.exe -m pytest -q` — all green on the **stub** (no tokens).
- A one-shot live smoke test of the new provider (like the ones used when building the
  application generator): one `analyze_job` and one `generate_application`, checking the
  dataclasses come back populated and grounded.
- Flip `AI_PROVIDER` in `.env`, confirm `/status` shows `ai_enabled: true` and a real score.

## What you do NOT touch

Services (`analysis_service`, `application_service`, `cv_service`), the API, the DB schema,
the worker, the prompts' *content*, and the entire web UI. If you find yourself editing any
of those to add a provider, the change has leaked out of the seam — stop and reconsider.

## Effort estimate

Step 1 ≈ 1h (+tests). Step 2 ≈ 30m. Steps 3–4 ≈ a couple of hours, most of it mapping the
SDK response into the existing dataclasses. Step 5 ≈ 30m. Half a day, contained.
