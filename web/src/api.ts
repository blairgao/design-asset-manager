import type {
  Asset,
  Board,
  Comment,
  Facets,
  Me,
  Page,
  Project,
  ProjectAccess,
  ProjectRole,
  SearchRequest,
  SearchResponse,
  Tag,
  UploadSession,
} from "./types";

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

/** RFC 9457 problem details as thrown by the API. */
export class Problem extends Error {
  status: number;
  title: string;
  detail: string | null;
  constructor(status: number, title: string, detail: string | null) {
    super(detail ?? title);
    this.name = "Problem";
    this.status = status;
    this.title = title;
    this.detail = detail;
  }
}

let activeFirmId: string | null = null;
export function setActiveFirm(id: string | null) {
  activeFirmId = id;
}
export function getActiveFirm() {
  return activeFirmId;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: { firm?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.firm !== false && activeFirmId) headers["X-Firm-Id"] = activeFirmId;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let title = res.statusText || "Error";
    let detail: string | null = null;
    try {
      const data = (await res.json()) as { title?: string; detail?: string | null };
      title = data.title ?? title;
      detail = data.detail ?? null;
    } catch {
      /* non-JSON error body */
    }
    throw new Problem(res.status, title, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // auth
  // MOCKED: always succeeds without calling the backend. Restore the real
  // request below when the magic-link endpoint is wired up.
  requestMagicLink: async (email: string): Promise<{ status: string }> => {
    console.info(`[mock] magic link "sent" to ${email}`);
    return { status: "sent" };
  },
  // requestMagicLink: (email: string) =>
  //   request<{ status: string }>("POST", "/auth/magic-link", { email }, { firm: false }),
  me: () => request<Me>("GET", "/me", undefined, { firm: false }),
  logout: () => request<void>("POST", "/auth/logout", undefined, { firm: false }),

  // projects
  listProjects: (firmId: string) => request<Project[]>("GET", `/firms/${firmId}/projects`),
  createProject: (firmId: string, body: { name: string; client_label?: string | null; phase?: string | null }) =>
    request<Project>("POST", `/firms/${firmId}/projects`, body),
  getProject: (id: string) => request<Project>("GET", `/projects/${id}`),
  updateProject: (id: string, body: Partial<Pick<Project, "name" | "client_label" | "phase" | "status">>) =>
    request<Project>("PATCH", `/projects/${id}`, body),
  listAccess: (id: string) => request<ProjectAccess[]>("GET", `/projects/${id}/access`),
  invite: (id: string, email: string, role: ProjectRole) =>
    request<ProjectAccess>("POST", `/projects/${id}/access`, { email, role }),
  revoke: (id: string, userId: string) => request<void>("DELETE", `/projects/${id}/access/${userId}`),

  // uploads
  startUpload: (body: { project_id: string; filename: string; mime: string; size: number; sha256?: string }) =>
    request<UploadSession>("POST", "/uploads", body),
  completeUpload: (assetId: string, parts: { part_number: number; etag: string }[], sha256?: string) =>
    request<{ status: string; deferred: boolean }>("POST", `/uploads/${assetId}/complete`, { parts, sha256 }),
  abortUpload: (assetId: string) => request<void>("DELETE", `/uploads/${assetId}`),

  // assets
  listAssets: (params: { project_id?: string; limit?: number; cursor?: string | null }) =>
    request<Page<Asset>>("GET", `/assets${qs(params)}`),
  getAsset: (id: string) => request<Asset>("GET", `/assets/${id}`),
  updateAsset: (
    id: string,
    body: { caption?: string | null; internal_only?: boolean; captured_at?: string | null; project_id?: string },
  ) => request<Asset>("PATCH", `/assets/${id}`, body),
  deleteAsset: (id: string) => request<void>("DELETE", `/assets/${id}`),
  downloadUrl: (id: string) => request<{ url: string; expires_in: number }>("GET", `/assets/${id}/download`),
  addTag: (id: string, namespace: string, value: string) =>
    request<Tag>("POST", `/assets/${id}/tags`, { namespace, value }),
  removeTag: (id: string, tagId: string) => request<void>("DELETE", `/assets/${id}/tags/${tagId}`),
  reprocess: (id: string) => request<{ status: string }>("POST", `/assets/${id}/reprocess`),
  favorite: (id: string) => request<void>("PUT", `/assets/${id}/favorite`),
  unfavorite: (id: string) => request<void>("DELETE", `/assets/${id}/favorite`),
  listComments: (id: string) => request<Comment[]>("GET", `/assets/${id}/comments`),
  addComment: (id: string, body: string) => request<Comment>("POST", `/assets/${id}/comments`, { body }),

  // search
  search: (body: SearchRequest) => request<SearchResponse>("POST", "/search", body),
  facets: (projectIds: string[]) => {
    const sp = new URLSearchParams();
    for (const p of projectIds) sp.append("project_id", p);
    const s = sp.toString();
    return request<{ facets: Facets }>("GET", `/search/facets${s ? `?${s}` : ""}`);
  },

  // boards
  listBoards: (projectId?: string) => request<Board[]>("GET", `/boards${qs({ project_id: projectId })}`),
  createBoard: (project_id: string, name: string) => request<Board>("POST", "/boards", { project_id, name }),
  getBoard: (id: string) => request<Board>("GET", `/boards/${id}`),
  updateBoard: (id: string, body: { name?: string; shared_with_clients?: boolean }) =>
    request<Board>("PATCH", `/boards/${id}`, body),
  deleteBoard: (id: string) => request<void>("DELETE", `/boards/${id}`),
  boardAssets: (id: string) => request<Asset[]>("GET", `/boards/${id}/assets`),
  setBoardAssets: (id: string, asset_ids: string[]) => request<void>("PUT", `/boards/${id}/assets`, { asset_ids }),
  addBoardAssets: (id: string, asset_ids: string[]) => request<void>("POST", `/boards/${id}/assets`, { asset_ids }),
};
