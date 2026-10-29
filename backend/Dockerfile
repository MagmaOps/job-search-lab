FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: bash for the entrypoint; build tools kept minimal (wheels cover the rest).
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Tests are included so they can run in CI / `docker compose run api pytest`.
COPY tests ./tests

COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Drop privileges.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]
