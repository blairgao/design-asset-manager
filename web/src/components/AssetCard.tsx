import { Link } from "react-router-dom";
import type { Asset } from "../types";

export function formatDuration(s: number | null): string {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export default function AssetCard({
  asset,
  matched,
  selected,
  onToggleSelect,
}: {
  asset: Asset;
  matched?: string[];
  selected?: boolean;
  onToggleSelect?: (id: string) => void;
}) {
  const busy = asset.status === "processing" || asset.status === "uploading";
  return (
    <div className={`card asset-card ${selected ? "selected" : ""}`}>
      <Link to={`/assets/${asset.id}`} className="thumb-link" aria-label={asset.filename}>
        {asset.thumb_url ? (
          <img src={asset.thumb_url} alt={asset.caption ?? asset.filename} loading="lazy" />
        ) : (
          <div className="thumb-placeholder">{asset.kind === "video" ? "▶" : "◻"}</div>
        )}
        {asset.kind === "video" && <span className="badge video">▶ {formatDuration(asset.duration_s)}</span>}
        {busy && <span className="badge processing">processing</span>}
        {asset.status === "failed" && <span className="badge failed">failed</span>}
        {asset.internal_only && <span className="badge internal">internal</span>}
        {asset.favorited && <span className="badge fav">★</span>}
      </Link>
      {onToggleSelect && (
        <label className="select-box">
          <input type="checkbox" checked={!!selected} onChange={() => onToggleSelect(asset.id)} />
        </label>
      )}
      <div className="asset-meta">
        <div className="asset-caption" title={asset.caption ?? asset.filename}>
          {asset.caption ?? asset.filename}
        </div>
        {matched && matched.length > 0 && (
          <div className="matched">
            {matched.map((m) => (
              <span key={m} className="chip tiny">{m.split(":")[1]}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
