import { useCallback, useRef, useState, type DragEvent } from "react";
import { uploadFile, type UploadProgress } from "../upload";

const FILE_CONCURRENCY = 3;

export default function UploadDropzone({
  projectId,
  onUploaded,
}: {
  projectId: string;
  onUploaded: (assetId: string) => void;
}) {
  const [items, setItems] = useState<Record<string, UploadProgress>>({});
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const report = useCallback((p: UploadProgress) => {
    setItems((prev) => ({ ...prev, [p.id]: p }));
  }, []);

  const run = useCallback(
    async (files: File[]) => {
      const queue = [...files];
      const worker = async () => {
        while (queue.length) {
          const f = queue.shift()!;
          try {
            const id = await uploadFile(f, projectId, report);
            onUploaded(id);
          } catch {
            /* reported via progress */
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(FILE_CONCURRENCY, files.length) }, worker));
    },
    [projectId, onUploaded, report],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const files = Array.from(e.dataTransfer.files).filter((f) => /^(image|video)\//.test(f.type) || /\.(heic|heif|mov)$/i.test(f.name));
    if (files.length) void run(files);
  };

  const list = Object.values(items).filter((i) => i.state !== "done");
  return (
    <div
      className={`dropzone ${over ? "over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept="image/*,video/*,.heic,.heif,.mov"
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (files.length) void run(files);
        }}
      />
      <div className="dropzone-inner">
        <span>Drop images or video here, or</span>
        <button className="btn" type="button" onClick={() => inputRef.current?.click()}>
          choose files
        </button>
      </div>
      {list.length > 0 && (
        <ul className="upload-list">
          {list.map((u) => (
            <li key={u.id} className={u.state === "error" ? "error" : ""}>
              <span className="upload-name">{u.filename}</span>
              <span className="muted">
                {u.state === "error" ? u.error : u.state === "hashing" ? "checking…" : u.state === "finishing" ? "finishing…" : `${Math.round((u.sent / u.bytes) * 100)}%`}
              </span>
              <progress value={u.sent} max={u.bytes} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
