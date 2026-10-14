import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Problem } from "../api";
import { useAuth } from "../auth";
import TagChips from "../components/TagChips";
import { formatDuration } from "../components/AssetCard";

function bytes(n: number) {
  if (n > 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n > 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${Math.round(n / 1e3)} KB`;
}

export default function AssetDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { isStaff, me } = useAuth();
  const asset = useQuery({
    queryKey: ["asset", id],
    queryFn: () => api.getAsset(id),
    refetchInterval: (q) => (q.state.data?.status === "processing" ? 3000 : false),
  });
  const comments = useQuery({ queryKey: ["comments", id], queryFn: () => api.listComments(id) });
  const [caption, setCaption] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["asset", id] });
    void qc.invalidateQueries({ queryKey: ["search"] });
  };
  const fail = (e: unknown) => setError(e instanceof Problem ? e.message : String(e));

  const favorite = useMutation({
    mutationFn: () => (asset.data?.favorited ? api.unfavorite(id) : api.favorite(id)),
    onSuccess: refresh,
    onError: fail,
  });
  const reprocess = useMutation({ mutationFn: () => api.reprocess(id), onSuccess: refresh, onError: fail });
  const remove = useMutation({
    mutationFn: () => api.deleteAsset(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["search"] });
      navigate(`/projects/${asset.data?.project_id}`);
    },
    onError: fail,
  });
  const saveCaption = useMutation({
    mutationFn: () => api.updateAsset(id, { caption }),
    onSuccess: () => {
      setCaption(null);
      refresh();
    },
    onError: fail,
  });
  const toggleInternal = useMutation({
    mutationFn: () => api.updateAsset(id, { internal_only: !asset.data?.internal_only }),
    onSuccess: refresh,
    onError: fail,
  });
  const addComment = useMutation({
    mutationFn: () => api.addComment(id, comment.trim()),
    onSuccess: () => {
      setComment("");
      void qc.invalidateQueries({ queryKey: ["comments", id] });
    },
    onError: fail,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && asset.data) navigate(`/projects/${asset.data.project_id}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [asset.data, navigate]);

  if (asset.isLoading) return <div className="center muted">Loading…</div>;
  if (asset.error || !asset.data) return <div className="center error">{String(asset.error ?? "Not found")}</div>;
  const a = asset.data;
  const canEdit = isStaff || a.uploader_id === me?.id;
  const poster = a.derived.find((d) => d.variant === "poster")?.url;
  const videoPreview = a.kind === "video" ? a.derived.find((d) => d.variant === "preview")?.url : null;

  const download = async () => {
    try {
      const { url } = await api.downloadUrl(id);
      window.open(url, "_blank", "noopener");
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div className="lightbox" role="dialog" aria-label={a.filename}>
      <div className="lightbox-media">
        <Link to={`/projects/${a.project_id}`} className="btn ghost close" aria-label="close">×</Link>
        {a.kind === "video" ? (
          videoPreview ? (
            <video src={videoPreview} poster={poster} controls autoFocus />
          ) : (
            <div className="thumb-placeholder big">{a.status === "processing" ? "Transcoding…" : "No preview"}</div>
          )
        ) : a.preview_url ? (
          <img src={a.preview_url} alt={a.caption ?? a.filename} />
        ) : (
          <div className="thumb-placeholder big">{a.status === "processing" ? "Processing…" : "No preview"}</div>
        )}
      </div>
      <aside className="lightbox-side">
        <div className="side-head">
          <div>
            <div className="filename" title={a.filename}>{a.filename}</div>
            <div className="muted small">
              {a.kind} · {bytes(a.bytes)}
              {a.width && a.height ? ` · ${a.width}×${a.height}` : ""}
              {a.duration_s != null ? ` · ${formatDuration(a.duration_s)}` : ""}
              {a.captured_at ? ` · shot ${new Date(a.captured_at).toLocaleDateString()}` : ""}
            </div>
            <div className="muted small">
              status <span className={`pill ${a.status}`}>{a.status}</span>
              {a.internal_only && <span className="pill internal">internal</span>}
            </div>
            {a.failure_reason && <p className="error small">{a.failure_reason}</p>}
          </div>
        </div>

        <div className="actions">
          <button className={`btn ${a.favorited ? "primary" : ""}`} onClick={() => favorite.mutate()} aria-pressed={a.favorited}>
            ★ {a.favorited ? "Favorited" : "Favorite"}
          </button>
          <Link className="btn" to={`/projects/${a.project_id}?similar_to=${a.id}`}>Find similar</Link>
          <button className="btn" onClick={() => void download()}>Download</button>
          {isStaff && (
            <>
              <button className="btn" onClick={() => reprocess.mutate()} disabled={a.status === "processing"}>Reprocess</button>
              <button className="btn" onClick={() => toggleInternal.mutate()}>{a.internal_only ? "Share with clients" : "Mark internal"}</button>
            </>
          )}
          {canEdit && (
            <button className="btn danger" onClick={() => window.confirm("Delete this asset?") && remove.mutate()}>Delete</button>
          )}
        </div>
        {error && <p className="error">{error}</p>}

        <section>
          <h3>Caption</h3>
          {caption === null ? (
            <p className="caption">
              {a.caption ?? <span className="muted">No caption yet.</span>}{" "}
              {canEdit && <button className="btn link" onClick={() => setCaption(a.caption ?? "")}>edit</button>}
            </p>
          ) : (
            <div>
              <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} />
              <div className="row">
                <button className="btn primary" onClick={() => saveCaption.mutate()}>Save</button>
                <button className="btn ghost" onClick={() => setCaption(null)}>Cancel</button>
              </div>
            </div>
          )}
        </section>

        {a.colors && a.colors.length > 0 && (
          <section>
            <h3>Colors</h3>
            <div className="swatches">
              {a.colors.map((c) => (
                <span key={c} className="swatch big" style={{ background: c }} title={c} />
              ))}
            </div>
          </section>
        )}

        <section>
          <h3>Tags</h3>
          <TagChips
            tags={a.tags}
            canEdit={canEdit}
            onAdd={async (ns, v) => {
              try {
                await api.addTag(id, ns, v);
                refresh();
              } catch (e) {
                fail(e);
              }
            }}
            onRemove={async (tid) => {
              try {
                await api.removeTag(id, tid);
                refresh();
              } catch (e) {
                fail(e);
              }
            }}
          />
        </section>

        {a.ocr_text && (
          <section>
            <h3>Text in image</h3>
            <p className="ocr">{a.ocr_text}</p>
          </section>
        )}

        <section>
          <h3>Comments</h3>
          <ul className="comments">
            {(comments.data ?? []).map((c) => (
              <li key={c.id}>
                <div className="comment-head">
                  <strong>{c.author_name ?? "Someone"}</strong>
                  <span className="muted small">{new Date(c.created_at).toLocaleString()}</span>
                </div>
                <div>{c.body}</div>
              </li>
            ))}
          </ul>
          <form
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              if (comment.trim()) addComment.mutate();
            }}
          >
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="Add a comment" />
            <button className="btn" disabled={!comment.trim() || addComment.isPending}>Post</button>
          </form>
        </section>
      </aside>
    </div>
  );
}
