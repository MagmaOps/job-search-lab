# Repo Comparison: Your App vs. `ai-job-search/`

> Comparison between **your project** (`backend/` FastAPI + `web/` Next.js + `deploy/` k3s,
> per `docs/design.md`) and the cloned **`ai-job-search/`** repo
> (`github.com/ai-job-search-dev/ai-job-search` — a Claude Code agent workflow).
>
> Goal context: **get a new job as a DevOps engineer (remote, EU).** Not building a product
> for others. Scores are weighted toward *that* goal, not toward general product-building.

---

## 1. What each one fundamentally is

| | **Your app** | **`ai-job-search/`** |
|---|---|---|
| Type | Deployed web application (always-on service) | Claude Code agent workflow (markdown skills + slash commands + CLI helpers) |
| Runtime | 24/7 on homelab k3s; scheduled collection | On-demand in a terminal (`/scrape`, `/apply`) |
| Core job | Collect → dedup → store → **rank** jobs into a dashboard | **Apply well**: tailor CV + cover letter, review, compile PDF, interview prep |
| AI | Anthropic behind an interface (stubbed for now) | Claude Code *is* the engine; repo is prompt methodology |
| Sources | RSS + free JSON APIs (RemoteOK, Remotive, Arbeitnow, WWR) | Danish portal scrapers + universal LinkedIn / freehire CLIs |
| Output | Match score, explanation, translated summary | Compiled 2-page CV PDF, 1-page cover letter, interview pack |

**They are complementary, not competitors.** One finds and ranks jobs; the other produces applications.

---

## 2. Feature-by-feature scoring

Scale: **0** = absent, **1** = minimal/partial, **2** = present, **3** = strong/best-in-class.
"Weight" reflects importance **to the DevOps-job goal**.

### Similar / overlapping features

| Feature | Weight | Your app | `ai-job-search/` | Notes |
|---|:---:|:---:|:---:|:---:|
| Automated job collection | 3 | **3** | 1 | Yours runs on a schedule; theirs is manual-trigger |
| Multiple job sources (modular) | 2 | **3** | 2 | Yours: clean `JobSource` registry. Theirs: per-portal CLIs |
| Deduplication (URL / id / fingerprint) | 2 | **3** | 1 | Core strength of your design; theirs tracks `seen_jobs.json` only |
| AI match scoring vs. CV | 3 | 2 | **3** | Yours stubbed-but-designed; theirs is a mature rubric |
| Multilingual / translation | 2 | **2** | 2 | Both handle it; yours persists translated summary |
| Persistent ranked dashboard | 2 | **3** | 1 | Yours = live DB + web UI; theirs = static HTML report |
| CV ingestion | 2 | 2 | **3** | Theirs cross-references diplomas/LinkedIn/references |
| Configurable AI provider | 1 | **2** | 1 | Yours provider-agnostic; theirs is Claude-only |
| Deployment story | 2 | **3** | 0 | Yours: Docker + k3s + CNPG HA. Theirs: local CLI only |

### Unique to **your app**

| Feature | Weight | Score | Notes |
|---|:---:|:---:|:---:|
| Always-on homelab service (k3s) | 3 | **3** | Matches your actual goal of a self-hosted collector |
| High availability (CNPG, leader election, PDB) | 1 | **3** | Over-engineered for the goal, but genuinely built |
| Content-hash "unchanged → skip" caching | 2 | **3** | Avoids repeat AI calls; well-specified |
| Status workflow (saved/dismissed/applied/interview) | 2 | **2** | In the dashboard; theirs tracks in CSV |
| Clean REST API surface | 1 | **2** | Reusable, testable |

### Unique to **`ai-job-search/`**

| Feature | Weight | Score | Notes |
|---|:---:|:---:|:---:|
| **Tailored CV + cover letter per job** | 3 | **3** | The part that actually lands interviews. You have *none* of this |
| Drafter → reviewer loop | 2 | **3** | Second agent critiques drafts before you send |
| PDF compile + layout verification | 2 | **3** | Catches orphaned titles, page overflow, font fallback |
| ATS text-layer check | 2 | **3** | Verifies what an ATS parser actually reads |
| Prompt-injection hardening of postings | 2 | **3** | `posting_guard.py` strips hidden text / invisible unicode |
| Interview prep + mock (`/interview`) | 2 | **3** | Stage-specific prep from the exact materials sent |
| Outcome tracking + follow-ups (`/outcome`) | 1 | **2** | Records results, drafts follow-ups |
| Salary benchmarking | 1 | **2** | Local JSON lookup, no network |
| Upskill / gap analysis | 1 | **2** | Maps skill gaps to a learning plan |

---

## 3. Weighted totals

Weighted score = Σ (feature weight × score), counting each repo only where it has the feature.

| Repo | Collection & ranking | Application & interview | Infra | **Total (weighted)** |
|---|:---:|:---:|:---:|:---:|
| **Your app** | **~34** | ~6 | **~12** | **~52** |
| **`ai-job-search/`** | ~13 | **~40** | 0 | **~53** |

> The totals land almost even — **because they win in opposite halves of the funnel.**
> Your app dominates *finding and ranking* jobs. Theirs dominates *applying and interviewing*.
> Neither is "just better"; they cover different stages.

---

## 4. Security result

| Check | Result |
|---|:---:|
| Provenance (git remote) | ✅ Legit public repo, no injected remotes |
| Token / data theft | ✅ None — all `fetch()` go to declared job-board hosts only |
| Third-party code on install | ✅ None — `--ignore-scripts`, no lifecycle hooks, no `trustedDependencies` |
| `child_process` / `exec` / `eval` in CLIs | ✅ None found |
| Permission model | ✅ Deny list blocks data-exfil shells + reads of `.env`/`~/.ssh`/`~/.aws` |
| Prompt-injection defense | ✅ `posting_guard.py` gate on all untrusted postings |

**Verdict: safe to use.** One caveat (not a code flaw): `/setup` writes personal data to
*tracked* files and GitHub forks are public — use a **private** repo or keep commits local.
It is an agent workflow, not a sandbox: on untrusted boards, skim what it fetched before sending.

---

## 5. Final result & recommendation

**Keep building your app. Borrow their methodology — don't adopt their repo.**

Your goal is a DevOps job on your own homelab, and your repo already matches that: working
`sources/` + `dedup` + `models` + `worker` + API + Next.js dashboard. Switching to
`ai-job-search/` would mean abandoning a working service for a Claude-Code-only CLI that
doesn't do always-on collection — the one thing your goal explicitly needs.

But their strongest idea is exactly your biggest gap. **Collecting and ranking jobs is the
easy half; applying well is the half that gets interviews.** Your `docs/design.md` stops at
a match score. Theirs produces a tailored CV, a reviewed cover letter, a verified PDF, and
interview prep — and the author reports 69 applications → 20 interviews → 1 offer with it.

### Concrete plan
1. **Add a tailored-application stage** to your AI pipeline — drafter→reviewer pattern, the
   "never invent qualifications" rule you already have, output to CV/cover-letter templates.
2. **Port the `posting_guard` idea** into your analysis step (hidden-text / injection stripping).
3. **Add `freehire-search`'s API** (`freehire.me`, no key, structured JSON, DevOps-heavy) as a
   new `JobSource` in your existing registry — the cleanest direct reuse available.
4. Treat their repo as a **reference you read**, not a dependency you run. There is nothing to
   merge; the value is in the prompts and the workflow shape.

### My thoughts
The honest tension: your project is the more impressive *engineering* (HA, CNPG, k3s), but for
the *actual goal* that infrastructure is polish on the easy half of the problem. If you want a
job faster, the highest-leverage move is not more collection — it's building the application
stage their repo proves out. Your app already wins at "what should I apply to." Close the loop
by making it also answer "and here's the application, ready to send."
