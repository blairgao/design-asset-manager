export type FirmRole = "admin" | "staff" | "client";
export type ProjectRole = "editor" | "viewer";
export type AssetKind = "image" | "video";
export type AssetStatus = "uploading" | "processing" | "ready" | "failed";
export type TagSource = "auto" | "manual";

export interface Membership {
  firm_id: string;
  firm_name: string;
  firm_slug: string;
  role: FirmRole;
}

export interface Me {
  id: string;
  email: string;
  name: string | null;
  memberships: Membership[];
  active_firm_id: string | null;
}

export interface Project {
  id: string;
  firm_id: string;
  name: string;
  client_label: string | null;
  phase: string | null;
  status: string;
  created_at: string;
  asset_count: number;
}

export interface ProjectAccess {
  user_id: string;
  email: string;
  name: string | null;
  role: ProjectRole;
}

export interface Tag {
  id: string;
  namespace: string;
  value: string;
  source: TagSource;
  confidence: number | null;
}

export interface Derived {
  variant: string;
  url: string;
  width: number | null;
  height: number | null;
  timestamp_s: number | null;
}

export interface Asset {
  id: string;
  project_id: string;
  kind: AssetKind;
  status: AssetStatus;
  filename: string;
  mime: string;
  bytes: number;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  internal_only: boolean;
  captured_at: string | null;
  created_at: string;
  uploader_id: string | null;
  caption: string | null;
  ocr_text: string | null;
  colors: string[] | null;
  tags: Tag[];
  thumb_url: string | null;
  preview_url: string | null;
  derived: Derived[];
  failure_reason: string | null;
  favorited: boolean;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface UploadSession {
  asset_id: string;
  upload_id: string | null;
  part_size: number;
  part_urls: string[];
  deduplicated: boolean;
}

export interface SearchFilters {
  project_id?: string[];
  kind?: AssetKind | null;
  room?: string[];
  phase?: string[];
  style?: string[];
  material?: string[];
  color?: string[];
  object?: string[];
  favorites_only?: boolean;
}

export interface SearchRequest {
  q?: string | null;
  similar_to?: string | null;
  filters: SearchFilters;
  limit?: number;
  cursor?: string | null;
}

export interface SearchHit {
  asset: Asset;
  score: number;
  matched_tags: string[];
  matched_timestamp_s: number | null;
}

export interface SearchResponse {
  hits: SearchHit[];
  next_cursor: string | null;
  mode: "semantic" | "similar" | "browse";
}

export interface FacetValue {
  value: string;
  count: number;
}

export type Facets = Record<string, FacetValue[]>;

export interface Board {
  id: string;
  project_id: string;
  name: string;
  shared_with_clients: boolean;
  created_by: string | null;
  created_at: string;
  asset_count: number;
  cover_url: string | null;
}

export interface Comment {
  id: string;
  asset_id: string;
  author_id: string | null;
  author_name: string | null;
  body: string;
  created_at: string;
}
