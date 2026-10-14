import { api } from "./api";

export interface UploadProgress {
  id: string;
  filename: string;
  bytes: number;
  sent: number;
  state: "hashing" | "uploading" | "finishing" | "done" | "error";
  assetId?: string;
  error?: string;
}

const HASH_LIMIT = 200 * 1024 * 1024;
const PART_CONCURRENCY = 4;

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function putPart(url: string, blob: Blob, onProgress: (loaded: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const etag = xhr.getResponseHeader("ETag") ?? "";
        resolve(etag.replace(/^"|"$/g, ""));
      } else reject(new Error(`part upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("network error during part upload"));
    xhr.send(blob);
  });
}

function mimeFor(file: File): string {
  if (file.type) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", heic: "image/heic", heif: "image/heif",
    webp: "image/webp", tif: "image/tiff", tiff: "image/tiff", mp4: "video/mp4", mov: "video/quicktime",
    webm: "video/webm",
  };
  return map[ext ?? ""] ?? "application/octet-stream";
}

/** Upload one file straight to S3 via presigned multipart URLs. */
export async function uploadFile(
  file: File,
  projectId: string,
  report: (p: UploadProgress) => void,
): Promise<string> {
  const id = crypto.randomUUID();
  const base: UploadProgress = { id, filename: file.name, bytes: file.size, sent: 0, state: "hashing" };
  report(base);
  try {
    const sha256 = file.size < HASH_LIMIT ? await sha256Hex(file) : undefined;
    const session = await api.startUpload({
      project_id: projectId,
      filename: file.name,
      mime: mimeFor(file),
      size: file.size,
      sha256,
    });
    if (session.deduplicated) {
      report({ ...base, sent: file.size, state: "done", assetId: session.asset_id });
      return session.asset_id;
    }
    report({ ...base, state: "uploading", assetId: session.asset_id });
    const loaded = new Array<number>(session.part_urls.length).fill(0);
    const etags = new Array<string>(session.part_urls.length);
    let next = 0;
    const worker = async () => {
      while (next < session.part_urls.length) {
        const i = next++;
        const start = i * session.part_size;
        const blob = file.slice(start, Math.min(file.size, start + session.part_size));
        etags[i] = await putPart(session.part_urls[i], blob, (l) => {
          loaded[i] = l;
          report({ ...base, state: "uploading", assetId: session.asset_id, sent: loaded.reduce((a, b) => a + b, 0) });
        });
        loaded[i] = blob.size;
      }
    };
    await Promise.all(Array.from({ length: Math.min(PART_CONCURRENCY, session.part_urls.length) }, worker));
    report({ ...base, state: "finishing", assetId: session.asset_id, sent: file.size });
    await api.completeUpload(
      session.asset_id,
      etags.map((etag, i) => ({ part_number: i + 1, etag })),
      sha256,
    );
    report({ ...base, state: "done", assetId: session.asset_id, sent: file.size });
    return session.asset_id;
  } catch (e) {
    report({ ...base, state: "error", error: e instanceof Error ? e.message : String(e) });
    throw e;
  }
}
