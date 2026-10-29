# Job Search Lab

A personal, self-hosted job-search application for a homelab k3s cluster. It collects
remote DevOps jobs from compliant sources (RSS feeds + free JSON APIs), stores them in
PostgreSQL, validates each job against a CV-derived matching profile using an AI model
(Anthropic), and shows ranked matches in a web dashboard.

See [`docs/design.md`](docs/design.md) for the full architecture and decisions, and
[`docs/kiro_job_search_task.md`](docs/kiro_job_search_task.md) for the original task.

## Components

| Service | Tech | Role |
|---------|------|------|
| `api` | FastAPI (Python 3.12) | REST API, CV extraction, business logic, DB access |
| `worker` | Python + APScheduler | Scheduled job collection + AI analysis queue (leader-elected) |
| `web` | Next.js | Dashboard, CV upload, query & profile management |
| database | PostgreSQL via CloudNativePG | HA data store (provided by `k3s-lab`) |

## Key decisions

- **Sources**: RSS + free JSON APIs only (We Work Remotely, RemoteOK, Remotive, Arbeitnow).
  No scraping. **LinkedIn is manual-only** — stored as a bookmark URL; you paste individual
  job URLs for analysis. See the design doc for why.
- **CV**: only the extracted text + derived matching profile are stored. The uploaded file
  is discarded after extraction.
- **AI**: Anthropic, configurable via env, key stays server-side. Runs with a `StubProvider`
  until a key is configured.
- **Deployment**: this repo builds a Docker image + a Kustomize base. The separate
  `k3s-lab` repo owns the CNPG operator, overlays, patches, secrets, and ingress.

## Local development

Requires Docker. The `docker-compose.yml` here is for **local dev only** — production runs
on k3s via `k3s-lab`.

```bash
cp .env.example .env     # fill in values (ANTHROPIC_API_KEY optional for stub mode)
docker compose up --build
```

- API: http://localhost:8000 (docs at `/docs`)
- Web: http://localhost:3000

## Configuration

All secrets stay server-side. See [`.env.example`](.env.example) for the full list.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres connection (CNPG `-rw` Service in prod) |
| `ANTHROPIC_API_KEY` | AI key; empty → stub provider |
| `AI_PROVIDER` / `AI_MODEL` | AI provider selection |
| `COLLECT_SCHEDULE` | Cron for scheduled collection (default every 6h) |
| `LEADER_ELECTION` | Worker HA leader election toggle |

## Deployment (k3s)

This repo produces:
1. Two **Docker images** on Docker Hub — `magmakomer/jobsearch-backend` (api + worker) and
   `magmakomer/jobsearch-web`.
2. A **Kustomize base** under `k8s/base/` with patch points and no homelab-specific values.
   The api and web are **Argo `Rollout`s** (blue-green); the worker is a leader-elected
   Deployment.

The separate `k3s-lab` repo consumes the base, installs the CloudNativePG and Argo
Rollouts operators, defines the `Cluster` CR, and applies overlays/patches/secrets/ingress.

### Build & push the images

One command (from the repo root) builds both (versioned) and pushes to Docker Hub:

```bash
./build-push.sh v1.0.0
# optional custom web API URL (baked into the Next.js bundle at build time):
./build-push.sh v1.0.0 http://jobsearch.lab.local/api
```

### What `k3s-lab` provides

The base references these by name; `k3s-lab` creates them:

- **CloudNativePG operator + `Cluster`** named `jobsearch-db`. CNPG gives you a primary
  plus replicas across nodes with **automatic failover**. It creates the
  `jobsearch-db-rw` Service (always the current primary) and the `jobsearch-db-app` Secret
  (with a ready-to-use `uri` key the app consumes as `DATABASE_URL`).
- **Secret `jobsearch-ai`** holding `ANTHROPIC_API_KEY` (seal it; optional — the app runs
  with a stub provider if absent).
- **Overlay** that patches the ingress host, `CORS_ORIGINS`, image tags, replicas, and
  resources.

The cluster-side wiring (ArgoCD `Application`, overlays, the CNPG `Cluster`, and the
`jobsearch-ai` sealed Secret) lives in the separate `k3s-lab` repo under
`apps/job-search-lab/`.

Render the base locally to inspect it:

```bash
kubectl kustomize k8s/base
```

### High availability

- **Stateless (api/web)**: 2 replicas, pod anti-affinity across nodes, PodDisruptionBudget.
- **Worker**: 2 replicas with `LEADER_ELECTION=true`; only the leader collects (Postgres
  advisory-lock election). If the leader's node dies, the standby takes over automatically.
- **Data**: CloudNativePG replication + automatic failover.

Because the only stateful component is Postgres (uploaded CV files are discarded after
text extraction), CNPG makes the whole data layer HA with no shared volume.

### Web API URL — build-time note

Next.js inlines `NEXT_PUBLIC_*` variables **at build time**. So the browser's API base is
fixed when you build the `jobsearch-web` image — set `NEXT_PUBLIC_API_URL` as a build arg
(as shown above) to your ingress path, e.g. `http://jobsearch.home.lan/api`. Patching the
env at runtime in the Deployment is not sufficient on its own.

### Database backups

Backups and restore are managed through CNPG in `k3s-lab` — enable `spec.backup` on the
`Cluster` to schedule backups to object storage (see the reference manifest). For an ad-hoc
dump: `kubectl exec` into the primary pod and run `pg_dump`.

## Tests

```bash
docker compose run --rm api pytest
```

Covered: URL normalization + dedup, content-hash skip logic, analysis caching/retries,
source parsers (fixtures), worker leader-election behavior.
