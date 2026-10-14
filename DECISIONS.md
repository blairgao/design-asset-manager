# Decision Log

Architecture decision records for the Design Asset Manager. Each record
captures a choice, the context that forced it, the alternatives considered,
and the consequences we accept. See [DESIGN.md](DESIGN.md) for the system
these decisions shape.

Conventions:

- One record per decision, numbered, never edited after acceptance. To change
  a decision, add a new record that supersedes the old one and update the old
  record's status line.
- Status is one of `Proposed`, `Accepted`, `Superseded by ADR-NNN`,
  `Deprecated`.
- Records are short. If a record needs more than a page, the decision is
  probably several decisions.

| # | Title | Status |
| --- | --- | --- |
| [ADR-001](#adr-001-python-backend-with-fastapi) | Python backend with FastAPI | Proposed |
| [ADR-002](#adr-002-postgresql-as-the-single-system-of-record) | PostgreSQL as the single system of record | Proposed |
| [ADR-003](#adr-003-direct-to-object-storage-uploads-with-presigned-urls) | Direct-to-object-storage uploads with presigned URLs | Proposed |
| [ADR-004](#adr-004-pgvector-for-similarity-search-no-separate-vector-store) | pgvector for similarity search, no separate vector store | Proposed |
| [ADR-005](#adr-005-claude-vision-for-categorization-with-a-controlled-vocabulary) | Claude vision for categorization with a controlled vocabulary | Proposed |
| [ADR-006](#adr-006-asynchronous-enrichment-via-a-job-queue) | Asynchronous enrichment via a job queue | Proposed |
| [ADR-007](#adr-007-multimodal-embeddings-behind-a-provider-adapter) | Multimodal embeddings behind a provider adapter | Proposed |
| [ADR-008](#adr-008-video-is-understood-through-sampled-keyframes) | Video is understood through sampled keyframes | Proposed |
| [ADR-009](#adr-009-logical-multi-tenancy-with-firm_id-on-every-row) | Logical multi-tenancy with firm_id on every row | Proposed |
| [ADR-010](#adr-010-auto-tags-never-overwrite-manual-tags) | Auto tags never overwrite manual tags | Proposed |
| [ADR-011](#adr-011-magic-link-authentication-no-passwords) | Magic-link authentication, no passwords | Proposed |
| [ADR-012](#adr-012-react-single-page-app-for-the-web-client) | React single-page app for the web client | Proposed |
| [ADR-013](#adr-013-aws-s3-for-object-storage) | AWS S3 for object storage | Accepted |

---

## ADR-001: Python backend with FastAPI

Date: 2026-10-14
Status: Proposed

### Context

The repository was initialized with a Python `.gitignore`. The enrichment
pipeline leans on ffmpeg, Pillow, and the official Anthropic SDK, all of which
have first-class Python support. The team is small and wants one language
across API and workers.

### Decision

Use Python 3.12+ for both the API service and the worker pool. FastAPI for
HTTP, Pydantic for schemas, SQLAlchemy 2.x with Alembic for persistence, and
`uv` for dependency management. One package, two entrypoints
(`api` and `worker`).

### Alternatives

- **TypeScript/Node end to end**: shares types with the frontend, but the
  image and video tooling is weaker and the SDK story for vision/embeddings is
  no better.
- **Go**: excellent for the API, poor for the ML-adjacent worker code.
- **Django**: batteries included, but the admin and ORM pull toward
  synchronous request handling and we want async I/O for presigned-URL and
  model calls.

### Consequences

- Async throughout the API; blocking work (ffmpeg, Pillow) runs in workers or
  thread pools, never in request handlers.
- Frontend and backend types are not shared automatically. The API publishes
  an OpenAPI schema and the client generates types from it.

---

## ADR-002: PostgreSQL as the single system of record

Date: 2026-10-14
Status: Proposed

### Context

We need relational data (firms, projects, ACLs), a tag graph, full-text, and
vector similarity. Operating several databases at v1 scale is more risk than
it buys.

### Decision

One PostgreSQL 16 database holds metadata, tags, ACLs, audit log, and
embeddings (via pgvector, ADR-004). Object storage holds bytes only. No
secondary search index at v1.

### Alternatives

- **Postgres + Elasticsearch/OpenSearch**: better text search and facets, but
  dual-write consistency and a second cluster to run.
- **Postgres + dedicated vector DB**: see ADR-004.
- **Document store**: tag and ACL queries are relational; a document store
  makes scoping harder, not easier.

### Consequences

- Facet counts are plain `GROUP BY` queries; acceptable to 100k assets per
  firm, revisit beyond that.
- Backups and migrations are one system. Alembic owns the schema.
- Full-text on captions uses Postgres `tsvector`, which is adequate because
  semantic search carries most of the load.

---

## ADR-003: Direct-to-object-storage uploads with presigned URLs

Date: 2026-10-14
Status: Proposed

### Context

Videos can be multi-GB. Streaming them through the API service would tie up
workers, double bandwidth, and make resumable uploads hard.

### Decision

The browser uploads directly to the AWS S3 bucket (ADR-013) using multipart
presigned URLs issued by the API. The API only sees the start and complete
calls. Originals are written once and never modified.

### Alternatives

- **Proxy through the API**: simple, but scales badly and makes every large
  upload a long-lived API request.
- **tus resumable-upload server**: good protocol, but another service to run
  when S3 multipart already gives resumability.

### Consequences

- The API must verify the object after `complete` (exists, size matches,
  checksum) because it never saw the bytes.
- CORS on the bucket must allow the web origin.
- Orphaned multipart sessions need a lifecycle rule to abort after 24 h.
- Local development targets a local S3 emulator (see ADR-013) so the code
  path is identical.

---

## ADR-004: pgvector for similarity search, no separate vector store

Date: 2026-10-14
Status: Proposed

### Context

Semantic and similar-image search need approximate nearest-neighbor queries
over embeddings, filtered by tenant and project. The filter is the hard part:
a vector store that returns the global top-k and then filters will miss
results for small projects.

### Decision

Store embeddings in pgvector with an HNSW index using cosine distance. Apply
tenant and project filters in the same SQL statement so filtering happens
before or alongside the index scan. Build a partial index per large firm if
a single global index becomes slow.

### Alternatives

- **Pinecone / Weaviate / Qdrant**: better raw ANN throughput and metadata
  filtering at very large scale, at the cost of a second system, dual writes,
  and a separate ACL model to keep in sync.
- **Brute-force in Postgres without an index**: fine under 10k vectors,
  unacceptable beyond.

### Consequences

- Vectors are 1024 to 1536 dimensions depending on the provider (ADR-007).
  At 100k assets per firm that is well within pgvector's comfort zone.
- Exit criterion: if p95 search latency exceeds 500 ms for a firm at 100k
  assets after tuning `ef_search` and partial indexes, open a new ADR for a
  dedicated store.

---

## ADR-005: Claude vision for categorization with a controlled vocabulary

Date: 2026-10-14
Status: Proposed

### Context

Auto-categorization must produce tags that are useful to designers: room
types, project phases, styles, materials. Open-ended captioning produces
inconsistent vocabulary ("sofa" vs "couch" vs "sectional") that breaks facets.
A classifier trained on a fixed label set would be consistent but cannot
read text in images, describe scenes, or adapt to a firm's own terminology.

### Decision

Use the Claude API (`claude-opus-5-5` via the official Python SDK) to
produce one structured JSON object per asset. The schema is enforced with
structured outputs and constrains namespaced tags to a controlled vocabulary
(global plus firm-specific), while allowing free-form `object` and `misc`
values and an open caption. Confidence is returned per tag and stored.

Request shape, kept stable for prompt caching:

1. System prompt: role, output rules, the full vocabulary (static, first).
2. User turn: project name and phase, then the image(s).
3. Adaptive thinking at `low` effort; this is a classification route, not a
   reasoning task. Server-side refusal fallbacks enabled so an occasional
   safety decline does not fail the job.
4. Batch API for backfills and bulk re-enrichment.

### Alternatives

- **Self-hosted open-vocabulary classifier (CLIP zero-shot over the
  vocabulary)**: cheap and fast, but no captions, no OCR, weak on
  compositional concepts like "mid-century lobby with brass accents". Kept in
  reserve as a cheap pre-filter if cost becomes a problem.
- **Fine-tuned image classifier**: consistent but rigid; every new vocabulary
  term is a retraining cycle.
- **A cheaper Claude model for the bulk route**: not chosen as the default.
  To be evaluated against a labeled sample once one exists; switching is a
  product owner decision, recorded as a new ADR.

### Consequences

- Per-asset enrichment cost is dominated by this call. Token usage is logged
  per asset and capped per firm per month (DESIGN.md section 11).
- Vocabulary changes require re-enrichment of affected assets; the stored
  `model_version` and prompt hash make the affected set queryable.
- The model never sees originals, only the 1600px preview with EXIF stripped.
- Prompt and schema live in version control next to the worker code and
  are covered by an eval set of labeled assets before any change ships.

---

## ADR-006: Asynchronous enrichment via a job queue

Date: 2026-10-14
Status: Proposed

### Context

Enrichment takes seconds for images and minutes for video. It must not block
the upload response, and it must survive worker restarts and model API
outages.

### Decision

Enrichment runs in a worker pool fed by a Redis-backed queue (arq or RQ;
pick during M2 based on retry and scheduling ergonomics). Two queues:
`images` and `video`, so long video jobs never starve image throughput.
Jobs are idempotent and keyed by `asset_id` plus pipeline version. Retries
use exponential backoff, five attempts, then dead-letter with the asset
marked `failed`.

### Alternatives

- **Celery + RabbitMQ**: mature, heavier to operate, more than v1 needs.
- **Postgres-backed queue (SKIP LOCKED)**: fewer moving parts and attractive;
  rejected for now because video jobs are long-running and visibility
  timeouts are awkward to model in SQL. Reconsider if Redis is the only
  reason to run Redis.
- **Managed queue (SQS)**: ties local development to cloud credentials.

### Consequences

- Redis is a required dependency. It is used only as a queue, never as a
  cache of record.
- The UI shows `processing` state and polls; WebSockets are deferred.
- Every pipeline step records its version so re-enrichment can be partial
  (for example re-embed only, without re-tagging).

---

## ADR-007: Multimodal embeddings behind a provider adapter

Date: 2026-10-14
Status: Proposed

### Context

Text-to-image search needs a joint embedding space where a text query and an
image land near each other. Providers differ in dimension, quality, pricing,
and hosting. We expect to change providers at least once.

### Decision

Define an `Embedder` interface with `embed_images(list[bytes])` and
`embed_text(list[str])` returning fixed-dimension vectors plus a model
identifier. Start with a hosted multimodal embedding API (Voyage multimodal
is the initial candidate). Record the model identifier on every embedding
row. Keep a self-hosted open model (SigLIP or OpenCLIP) as the second
implementation so the adapter is exercised from day one.

### Alternatives

- **Text-only embeddings over the caption**: loses visual similarity and
  everything the caption omits. Kept as a secondary vector for text-heavy
  queries.
- **Commit to one hosted provider without an adapter**: fastest, but a
  provider change becomes a rewrite plus a full re-embed under pressure.

### Consequences

- A provider change still requires re-embedding every asset; the adapter
  only removes the code change. Re-embedding is a batch job tracked by
  the `model` column.
- Vectors from different models are never compared. Search uses the current
  model only and ignores rows embedded by older models until backfilled.

---

## ADR-008: Video is understood through sampled keyframes

Date: 2026-10-14
Status: Proposed

### Context

Walkthrough videos are long, large, and mostly redundant frame to frame.
Sending whole videos to a model is expensive and unnecessary for tagging.

### Decision

Workers extract keyframes with ffmpeg scene-change detection, capped at one
frame per five seconds and sixty frames per video. Keyframes are sent to the
vision model as one multi-image request. Each keyframe gets its own
embedding; the video gets a mean-pooled vector for coarse similarity and the
per-keyframe vectors for "jump to the moment" search.

### Alternatives

- **Native video input to a model**: simpler pipeline, but cost scales with
  duration and the result is harder to attach to a timestamp.
- **Fixed-interval sampling only**: misses short scenes; scene detection
  with a cap is cheap and better.
- **Audio transcription**: useful for narrated walkthroughs; deferred to a
  later ADR because most site videos have no useful speech.

### Consequences

- A 10-minute walkthrough costs roughly as much to enrich as 60 images.
- Keyframe count is a tuning knob exposed in config, not code.

---

## ADR-009: Logical multi-tenancy with firm_id on every row

Date: 2026-10-14
Status: Proposed

### Context

Firms must never see each other's assets. Clients of one firm may also be
clients of another, so users are global and membership is per firm.

### Decision

One database and one bucket per environment. Every tenant-owned table carries
`firm_id`, including high-volume tables where it is denormalized. All
repository functions take a resolved `Viewer` and apply `firm_id` and
project scoping; handlers cannot construct unscoped queries. Object keys are
prefixed `firms/{firm_id}/`. Postgres row-level security is planned as a
second line of defense once the schema settles.

### Alternatives

- **Schema per tenant**: strong isolation, painful migrations and
  connection pooling at hundreds of firms.
- **Database per tenant**: strongest isolation, operationally expensive, and
  cross-tenant users become awkward.

### Consequences

- Tenant scoping is a code convention until RLS lands. Integration tests
  include a cross-tenant access suite that must stay green.
- Reporting across firms (for us, not for customers) is trivial.

---

## ADR-010: Auto tags never overwrite manual tags

Date: 2026-10-14
Status: Proposed

### Context

Designers will correct tags. If re-enrichment silently reverts corrections,
trust in the system collapses and nobody corrects anything.

### Decision

Every `asset_tag` row records `source` as `auto` or `manual`. Re-enrichment
may add, update, or remove `auto` rows only. Removing a tag that was `auto`
creates a `manual` suppression record so the same tag is not re-added. Manual
edits are written to the audit log.

### Alternatives

- **Last writer wins**: simplest, unacceptable for the reason above.
- **Lock the asset after any manual edit**: loses the benefit of improved
  models on everything a human ever touched.

### Consequences

- Tag queries must consider suppressions; this is encapsulated in the
  repository layer.
- Manual corrections become labeled data for evaluating prompt and model
  changes (ADR-005).

---

## ADR-011: Magic-link authentication, no passwords

Date: 2026-10-14
Status: Proposed

### Context

Clients are occasional users invited by email. Password onboarding is the
step where client participation dies. Firm staff may later want SSO.

### Decision

Email magic links for all users at v1, with sessions in signed HTTP-only
cookies. Invitations and logins are the same flow. Reserve an `identity`
table so OIDC/SSO for firms can be added without touching `user`.

### Alternatives

- **Passwords plus reset flow**: familiar but higher friction and a credential
  store to protect.
- **Third-party auth service**: fast to start, adds a vendor to the critical
  path of every login; revisit when SSO is required.

### Consequences

- Transactional email delivery is on the critical path. Use a provider with
  delivery monitoring from day one.
- Links expire in 15 minutes and are single-use.

---

## ADR-012: React single-page app for the web client

Date: 2026-10-14
Status: Proposed

### Context

The client is a media-heavy, interaction-heavy app: drag-and-drop upload with
progress, virtualized grids of thumbnails, lightbox and video player, facet
filtering. It is behind a login, so search engine indexing is irrelevant.

### Decision

React with TypeScript, built with Vite, served as static files from the CDN.
Types are generated from the API's OpenAPI schema. No server-side rendering.

### Alternatives

- **Next.js**: SSR and routing conventions we do not need behind a login,
  and a Node server to run.
- **Server-rendered templates with HTMX**: lighter stack, but the upload and
  grid interactions push against its limits quickly.

### Consequences

- The API must serve a correct OpenAPI document; it is part of the contract
  and checked in CI.
- Mobile is responsive web only at v1 (DESIGN.md open questions).

---

## ADR-013: AWS S3 for object storage

Date: 2026-10-14
Status: Accepted

### Context

The service stores large, immutable binary assets (originals up to 10 GB)
plus regenerable derived files, and must serve previews to browsers at low
latency worldwide. Uploads bypass the API (ADR-003), so the storage layer
must support browser-direct multipart uploads with resumability. The
decision to use S3 was made by the project owner.

### Decision

Use AWS S3 as the only object store.

- One bucket per environment (`dam-dev`, `dam-staging`, `dam-prod`), private,
  with Block Public Access on and SSE-S3 encryption at rest.
- Key layout: `firms/{firm_id}/originals/{asset_id}/{sha256}.{ext}` and
  `firms/{firm_id}/derived/{asset_id}/{variant}.{ext}`. The firm prefix is
  the tenant boundary for IAM conditions and for per-firm lifecycle rules.
- Bucket versioning on. Lifecycle rules: abort incomplete multipart uploads
  after 24 h; transition soft-deleted originals to Glacier Instant Retrieval
  after 30 days and expire them after 90; derived files are never archived
  because they are cheap to regenerate.
- Previews and thumbnails are served through CloudFront with signed URLs
  and an origin access control. Originals are served only through
  short-lived presigned S3 URLs issued after the access check.
- Access from the API and workers uses IAM roles, never static keys. The API
  role may create presigned URLs and read object metadata; the worker role
  may read originals and write derived files; neither may delete outside
  the tombstone flow.
- Local development runs MinIO as an S3 emulator through the same `boto3`
  client with an endpoint override, so no code path differs by environment.

### Alternatives

- **Any S3-compatible store (MinIO, Cloudflare R2, Backblaze B2)**: cheaper
  egress on R2 and B2, but weaker integration with CloudFront signed URLs,
  IAM, and lifecycle tiering. The `boto3` client keeps the door open; a move
  would be an infrastructure change, not a code rewrite.
- **Google Cloud Storage / Azure Blob**: comparable features, but the rest of
  the stack (RDS for Postgres, ElastiCache for Redis) is simplest on AWS.
- **Database BLOBs**: not viable at multi-GB object sizes.

### Consequences

- The deployment is AWS-centric. Postgres and Redis should be hosted on AWS
  in the same region to avoid cross-cloud egress on every enrichment job.
- Egress cost is the main cost lever for a media-heavy product. CloudFront
  caching of previews and WebP derived files keep most reads off S3.
- Per-firm storage usage is computed from S3 Inventory reports rather than by
  listing objects, which is slow at scale.
- A region is chosen at bucket creation. Data residency for firms outside
  that region is out of scope for v1 and would need a new ADR.
