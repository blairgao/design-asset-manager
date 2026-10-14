# Design: Design Asset Manager

Status: Draft v0.1 (2026-10-14)
Owner: Blair Gao
Related: [DECISIONS.md](DECISIONS.md) for the rationale behind each choice.

## 1. Problem

Architecture and interior design firms accumulate large volumes of visual
material: site photos, renders, mood-board references, material samples,
construction progress shots, walkthrough videos, and client-supplied
inspiration. Today this lives in shared drives, chat threads, and email.
Nobody can find "that terrazzo sample from the lobby concept" six months
later, and clients have no clean way to contribute or review.

The service lets a firm and its clients upload image and video assets into
shared projects, then find them again by **meaning** (natural-language and
visual search) rather than by remembering a filename or folder. Assets are
**categorized automatically** on upload so the library stays organized without
anyone filing things by hand.

## 2. Goals and non-goals

### Goals

- Upload images and video from browser and mobile, including large files
  (multi-GB video) with resumable transfer.
- Automatically tag every asset: room type, project phase, style, materials,
  colors, dominant objects, text found in the image, and a short caption.
- Search by free text ("warm oak kitchen with black fixtures"), by similar
  image, and by structured filters (project, client, phase, room, material).
- Multi-tenant: each firm is isolated. Clients see only the projects they are
  invited to.
- Lightweight review: clients can comment and mark favorites on assets.
- Audit trail: who uploaded, who changed tags, when.

### Non-goals (v1)

- CAD/BIM file handling (DWG, RVT, IFC). Treat as opaque attachments if at all.
- Full design-review markup tooling (redlines, annotations on drawings).
- Billing and self-serve subscription. Firms are onboarded manually at first.
- Real-time collaboration or presence.
- On-prem deployment.

## 3. Users and core flows

| Persona | Needs |
| --- | --- |
| Designer / architect (firm staff) | Dump a camera roll into a project, find references fast, curate boards for clients. |
| Project lead (firm admin) | Manage projects, invite clients, control what clients see, correct auto-tags. |
| Client | Upload inspiration, browse what the firm shares, favorite and comment. |

Core flows:

1. **Upload**: user drags files into a project. Files go straight to object
   storage via presigned URLs. A record is created, processing is queued, and
   the asset appears immediately with a "processing" badge.
2. **Enrich**: a worker generates thumbnails and previews, extracts metadata,
   runs the vision model for tags and caption, computes embeddings, and marks
   the asset ready.
3. **Find**: user types a query or picks "find similar". Results combine
   vector similarity with structured filters, scoped to what the user may see.
4. **Curate**: user corrects tags, groups assets into boards, shares a board
   with a client.

## 4. Architecture overview

```
 Browser / mobile web (React SPA)
        |  HTTPS / JSON
        v
 +---------------------+       presigned PUT        +----------------------+
 |  API service        | <------------------------- |  AWS S3              |
 |  FastAPI (Python)   | --- enqueue job --------+  |  originals, derived  |
 +---------------------+                         |  +----------------------+
        |                                        v              ^
        |  SQL                            +--------------+      |
        v                                 | Job queue    |      |
 +---------------------+                  | (Redis)      |      |
 | PostgreSQL          |                  +--------------+      |
 |  + pgvector         | <--- writes ---  +--------------+      |
 |  metadata, tags,    |                  | Worker pool  | -----+
 |  embeddings, ACLs   |                  | (Python)     |
 +---------------------+                  +--------------+
                                                 |
                                   +-------------+--------------+
                                   |                            |
                                   v                            v
                          Claude API (vision)          Embedding service
                          tags, caption, OCR           image + text vectors
```

Components:

- **Web client**: single-page app. Handles chunked, resumable uploads directly
  to storage, shows processing state via polling (WebSockets later if needed).
- **API service**: stateless Python service (FastAPI). Auth, authorization,
  CRUD for firms/projects/assets/boards, search endpoint, presigned URL issuer,
  job enqueuer.
- **Worker pool**: same codebase, different entrypoint. Consumes jobs from the
  queue and runs the enrichment pipeline. Horizontally scalable; video jobs
  run on a separate queue so they do not starve image jobs.
- **PostgreSQL + pgvector**: single system of record for metadata, ACLs, tags,
  and vectors. One database, logical tenant isolation by `firm_id`.
- **Object storage**: AWS S3, one bucket per environment (ADR-013). Originals
  are immutable and live under `firms/{firm_id}/originals/`. Derived files
  (thumbnails, previews, keyframes) are regenerable and live under
  `firms/{firm_id}/derived/`. Previews are served through CloudFront with
  signed URLs; originals are downloaded via short-lived presigned S3 URLs.
- **External model APIs**: Claude for vision understanding, a multimodal
  embedding model for similarity search. Both behind thin adapters so they can
  be swapped.

## 5. Data model

Core entities (simplified):

```
firm            id, name, slug, plan, created_at
user            id, email, name, created_at
membership      user_id, firm_id, role (admin | staff | client)
project         id, firm_id, name, client_firm_label, status, created_at
project_access  project_id, user_id, role (editor | viewer)
asset           id, firm_id, project_id, uploader_id, kind (image | video),
                storage_key, mime, bytes, width, height, duration_s,
                sha256, status (uploading | processing | ready | failed),
                captured_at, created_at, deleted_at
asset_derived   asset_id, variant (thumb | preview | keyframe_n), storage_key
asset_tag       asset_id, tag_id, source (auto | manual), confidence,
                created_by, created_at
tag             id, firm_id (null = global), namespace, value
                namespaces: room, phase, style, material, color, object, misc
asset_text      asset_id, caption, ocr_text, model_version
asset_embedding asset_id, model, vector (pgvector), created_at
board           id, firm_id, project_id, name, created_by
board_asset     board_id, asset_id, position
comment         id, asset_id, author_id, body, created_at
favorite        asset_id, user_id
audit_log       id, firm_id, actor_id, action, target_type, target_id,
                payload, created_at
```

Notes:

- `firm_id` is denormalized onto high-volume tables so every query can filter
  by tenant without joins, and so Postgres row-level security can be enabled
  later without a schema change.
- Tags are two-part (`namespace`, `value`) so the UI can render facets and the
  categorizer can be constrained to a vocabulary per namespace. Global tags
  form the shared vocabulary; firm-scoped tags cover house terminology.
- `sha256` enables dedupe within a firm: an identical re-upload links to the
  existing storage object instead of reprocessing.
- Soft delete on assets. Hard delete of storage objects runs as a scheduled
  job after a retention window.

## 6. Upload pipeline

1. Client calls `POST /uploads` with filename, size, mime, project.
   API validates quota and permissions, creates an `asset` row in
   `uploading` state, and returns a multipart presigned upload session.
2. Client uploads parts directly to object storage. Parts are retried
   independently; the session can resume after a page reload.
3. Client calls `POST /uploads/{id}/complete`. API verifies the object exists,
   records size and checksum, flips status to `processing`, and enqueues
   `enrich_asset`.
4. Worker runs the enrichment pipeline (section 7). On success status becomes
   `ready`. On a hard failure status becomes `failed` with a reason; a retry
   can be triggered from the UI.

Limits (v1): images up to 200 MB, video up to 10 GB. Accepted formats: JPEG,
PNG, HEIC, WebP, TIFF; MP4, MOV, WebM. HEIC and TIFF are transcoded to JPEG
for previews; originals are kept untouched.

## 7. Enrichment pipeline

Each step is idempotent and records its model/tool version so assets can be
re-enriched when models improve.

### Images

1. **Probe**: read dimensions, EXIF (captured time, camera, GPS). GPS is
   stored but never exposed to clients by default.
2. **Derive**: 256px thumbnail, 1600px preview, both WebP. Strip EXIF from
   derived files.
3. **Understand** (Claude vision call on the preview):
   - Output a strict JSON object via structured outputs: caption, tags per
     namespace drawn from the controlled vocabulary, free-form objects, OCR
     text, dominant colors as hex, and a per-tag confidence.
   - The prompt includes the firm's vocabulary and the project's name and
     phase so tags are grounded in context.
4. **Embed**: compute an image embedding of the preview and a text embedding
   of the caption + tags. Both are stored; search queries the image vector by
   default and falls back to text when the modality demands it.
5. **Persist**: write tags with `source = auto` and confidences, text, and
   vectors in one transaction. Auto tags never overwrite manual tags.

### Video

1. **Probe**: duration, resolution, codec.
2. **Derive**: poster frame, 720p preview MP4 (H.264), and keyframes sampled
   by scene change (ffmpeg scene detection) capped at 1 frame per 5 seconds
   and 60 frames total.
3. **Understand**: run the image understanding step on the keyframes as a
   single multi-image request so the model sees the whole walkthrough.
   Video-level tags are the union with aggregated confidence; per-keyframe
   results are kept to support "jump to the moment" in search.
4. **Embed**: one embedding per keyframe plus a mean-pooled video vector.

### Model usage

- Vision model: `claude-opus-5-5` through the official Python SDK, with
  structured outputs for the tag schema, adaptive thinking at `low` effort for
  the classification route, and server-side refusal fallbacks enabled.
- Backfills and re-enrichment of existing libraries go through the Message
  Batches API, which halves cost and is not latency sensitive.
- The controlled vocabulary and system prompt are static and placed first in
  the request so prompt caching applies across every asset in a run.
- The embedding provider sits behind an adapter interface (see DECISIONS.md,
  ADR-007). Changing it requires a full re-embed, tracked by `model` on the
  embedding row.

## 8. Search

A single `POST /search` endpoint takes:

```
{ "q": "warm oak kitchen",            # optional free text
  "similar_to": "<asset_id>",          # optional image-to-image
  "filters": { "project_id": [...], "room": [...], "phase": [...],
               "material": [...], "kind": "image" },
  "limit": 50, "cursor": "..." }
```

Execution:

1. Resolve the set of projects the caller may read. Every subsequent query is
   constrained to that set and to the caller's `firm_id`.
2. If `q` is present, embed it with the text tower of the multimodal model
   and run an approximate nearest-neighbor query (pgvector HNSW, cosine)
   against `asset_embedding`, pre-filtered by the SQL filters.
3. If `similar_to` is present, use that asset's stored vector instead.
4. If only filters are present, return by recency.
5. Rerank the top 200 candidates with a simple blend: vector score, exact tag
   matches extracted from `q` (a lexical pass over the vocabulary), and a
   recency prior. Return with highlighted matched tags so users understand
   why a result appeared.

Facet counts for the filter sidebar come from a separate aggregate query over
`asset_tag` scoped the same way.

Target: p95 under 500 ms for a firm with 100k assets. HNSW with a partial
index per `firm_id` keeps this tractable; move to a dedicated vector store
only if that target is missed (ADR-004).

## 9. Access control

- Roles: firm `admin`, firm `staff`, `client`.
- Admins and staff see all projects in their firm.
- Clients see only projects they have `project_access` to, and within those
  only assets that are not marked internal-only. Boards can be shared to a
  client explicitly.
- Every API handler receives a resolved `Viewer` object and passes it to the
  repository layer. Repositories apply tenant and project scoping; handlers
  never build unscoped queries.
- Presigned download URLs are short-lived (15 min) and issued only after the
  same scoping check.

## 10. API surface (v1)

```
POST   /auth/magic-link            email login, no passwords
GET    /me
GET    /firms/{id}/projects
POST   /firms/{id}/projects
POST   /projects/{id}/access       invite user to project
POST   /uploads                    start multipart upload
POST   /uploads/{id}/complete
GET    /assets/{id}
PATCH  /assets/{id}                caption, internal flag, captured_at
DELETE /assets/{id}                soft delete
POST   /assets/{id}/tags           add manual tag
DELETE /assets/{id}/tags/{tag_id}
POST   /assets/{id}/reprocess
POST   /search
GET    /search/facets
CRUD   /boards, /boards/{id}/assets
POST   /assets/{id}/comments
PUT    /assets/{id}/favorite
```

JSON over HTTPS, cursor pagination everywhere, errors as RFC 9457 problem
details.

## 11. Operational concerns

- **Observability**: structured logs with `firm_id`, `asset_id`, `job_id`;
  OpenTelemetry traces across API, queue, and worker; per-step enrichment
  timings and model token usage recorded as metrics.
- **Cost controls**: per-firm monthly enrichment budget. Over budget, uploads
  still succeed but enrichment queues at low priority and the admin is
  notified. Model token usage is logged per asset for attribution.
- **Failure handling**: jobs retry with exponential backoff, max 5 attempts,
  then dead-letter. A failed enrichment never blocks viewing the original.
- **Backups**: daily Postgres snapshots, 30-day retention. S3 bucket
  versioning is on; soft-deleted originals move to Glacier Instant Retrieval
  after 30 days and are purged after 90 via lifecycle rules.
- **Privacy**: EXIF GPS is stripped from anything a client can download.
  Site photos may contain people; no face recognition is performed and the
  vision prompt instructs the model not to identify individuals.
- **Secrets**: model API keys live only in the worker environment. The API
  service never calls the model directly.

## 12. Open questions

- Should clients be allowed to create their own projects, or only contribute
  to firm-created ones? Current assumption: contribute only.
- Do firms need a per-firm controlled vocabulary editor in v1, or is a global
  vocabulary with free-form `misc` tags enough?
- Is mean-pooled video embedding good enough for "find similar walkthrough",
  or should video search always go keyframe-first?
- Mobile: responsive web only, or a thin native wrapper for camera-roll
  upload? Responsive web is the v1 assumption.

## 13. Milestones

1. **M1 Skeleton**: auth, firms, projects, direct-to-storage upload, asset
   grid with thumbnails. No AI.
2. **M2 Enrichment**: worker pipeline for images, auto tags, caption, facets.
3. **M3 Search**: embeddings, semantic and similar-image search, reranking.
4. **M4 Video**: keyframe pipeline, preview transcoding, video search.
5. **M5 Client collaboration**: boards, sharing, comments, favorites.
