# design-asset-manager

Web service for architecture and interior design firms and their clients to upload image and video assets, with smart lookup and automatic categorization.

- [DESIGN.md](DESIGN.md) — system design: goals, architecture, data model, upload and enrichment pipelines, search, access control, API.
- [DECISIONS.md](DECISIONS.md) — architecture decision records with context, alternatives, and consequences.
- [web/README.md](web/README.md) — the React client.

## Layout

```
src/dam/
  main.py            FastAPI app (dam-api)
  worker.py          arq workers for the image and video queues (dam-worker)
  cli.py             admin CLI: firms, members, vocabulary, re-enrichment (dam-admin)
  models.py          SQLAlchemy models (DESIGN.md section 5)
  viewer.py          resolved caller + tenant/project scoping (ADR-009)
  deps.py            request dependencies; the fixed local user (no sign-in yet, ADR-011)
  storage.py         S3 keys, multipart presigning, CloudFront signing (ADR-013)
  queue.py           job enqueueing (ADR-006)
  routers/           HTTP handlers; every handler goes through a Viewer
  repositories/      all SQL; tag merge rules (ADR-010), vector search + rerank
  enrichment/        images (Pillow), video (ffmpeg), vision (Claude), embeddings, pipeline
alembic/             migrations
tests/               unit tests (no database required)
web/                 React + TypeScript client (ADR-012)
```

## Local development

Prerequisites: Python 3.12+, `uv`, Node 20+, `ffmpeg`/`ffprobe`, Docker.

```bash
# 1. Dependencies: Postgres (pgvector), Redis, MinIO as the local S3.
docker compose up -d

# 2. Python environment and config.
uv venv --python 3.12 && uv pip install -e ".[dev]"
cp .env.example .env            # defaults match docker-compose.yml
#    Set ANTHROPIC_API_KEY (worker only) and VOYAGE_API_KEY, or use
#    DAM_EMBEDDING_PROVIDER=fake to run without an embedding key.

# 3. Schema and vocabulary.
uv run alembic upgrade head
uv run dam-admin seed-vocabulary

# 4. Run the three processes. There is no sign-in yet: the first request creates a local
#    admin user and firm (DAM_LOCAL_USER_EMAIL / DAM_LOCAL_FIRM_SLUG in .env).
uv run dam-api                  # http://localhost:8000, OpenAPI at /docs
uv run dam-worker images
uv run dam-worker video

# 5. The web client.
cd web && npm install && npm run dev    # http://localhost:5173
```

Tests and lint:

```bash
uv run pytest
uv run ruff check src tests
```

## Operations

- **Re-enrich a firm** after a vocabulary or prompt change: `dam-admin reenrich --firm <slug>`. Jobs are queued at low priority; manual tags are never overwritten.
- **Budgets**: when a firm exceeds its monthly token budget (`DAM_MONTHLY_ENRICHMENT_BUDGET_TOKENS` or the per-firm override), uploads still succeed and enrichment is deferred.
- **Production storage**: leave `DAM_S3_ENDPOINT_URL` empty, give the API and worker IAM roles, and set the CloudFront variables so derived files are served from the CDN (ADR-013).
- **No sign-in yet** (ADR-011): every request runs as the local admin user. Do not expose the API on a public network until authentication exists.

## Developing the client without the backend

`scripts/mock_api.py` is an in-memory stand-in for the API with seeded projects, assets,
boards and comments. It needs no database, storage, or model keys:

```bash
uv run python scripts/mock_api.py      # http://localhost:8000
cd web && npm run dev                  # http://localhost:5173
```

Screenshots of the client running against it are in `docs/screenshots/`.

## Deploying the demo to Render

`render.yaml` is a Render Blueprint that deploys the mock API as a Python web service and the
client as a static site, with the client's `VITE_API_BASE` wired to the API's hostname. In the
Render dashboard choose **New → Blueprint**, pick this repository, and apply. Data lives in
memory on the API instance, so it resets on each deploy or restart, and video uploads fail
there because the native Python runtime has no ffmpeg. Image and HEIC uploads work.
