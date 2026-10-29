#!/usr/bin/env bash
# Build and push both images to Docker Hub under the magmakomer namespace.
#
# Usage (run from the repo root):
#   ./build-push.sh v1.0.1
#   ./build-push.sh v1.0.1 http://jobsearch.lab.local/api   # custom web API URL
#
# NEXT_PUBLIC_API_URL is baked into the web image at build time (Next.js inlines
# NEXT_PUBLIC_* during `next build`), so it must be the real ingress API URL the browser
# will call — not a runtime value. Default matches the k3s-lab *.lab.local convention.
set -euo pipefail

VERSION="${1:?usage: ./build-push.sh <version> [web_api_url]   e.g. ./build-push.sh v1.0.1}"
WEB_API_URL="${2:-http://jobsearch.lab.local/api}"
REGISTRY="magmakomer"

# This script lives at the repo root; backend/ and web/ are siblings beside it.
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo ">> building backend $REGISTRY/jobsearch-backend:$VERSION"
docker build \
  -t "$REGISTRY/jobsearch-backend:$VERSION" \
  -t "$REGISTRY/jobsearch-backend:latest" \
  "$ROOT/backend"

echo ">> building web $REGISTRY/jobsearch-web:$VERSION (NEXT_PUBLIC_API_URL=$WEB_API_URL)"
docker build \
  --build-arg "NEXT_PUBLIC_API_URL=$WEB_API_URL" \
  -t "$REGISTRY/jobsearch-web:$VERSION" \
  -t "$REGISTRY/jobsearch-web:latest" \
  "$ROOT/web"

echo ">> pushing"
docker push "$REGISTRY/jobsearch-backend:$VERSION"
docker push "$REGISTRY/jobsearch-backend:latest"
docker push "$REGISTRY/jobsearch-web:$VERSION"
docker push "$REGISTRY/jobsearch-web:latest"

echo ">> done. Bump the image tags in k3s-lab apps/job-search-lab/workload/prod/kustomization.yaml to $VERSION"
