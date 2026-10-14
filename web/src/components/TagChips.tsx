import { useState, type FormEvent } from "react";
import type { Tag } from "../types";

const ORDER = ["room", "phase", "style", "material", "color", "object", "misc"];

export default function TagChips({
  tags,
  canEdit,
  onAdd,
  onRemove,
}: {
  tags: Tag[];
  canEdit: boolean;
  onAdd: (namespace: string, value: string) => Promise<void>;
  onRemove: (tagId: string) => Promise<void>;
}) {
  const [ns, setNs] = useState("misc");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const groups = new Map<string, Tag[]>();
  for (const t of tags) groups.set(t.namespace, [...(groups.get(t.namespace) ?? []), t]);
  const names = [...ORDER.filter((n) => groups.has(n)), ...[...groups.keys()].filter((n) => !ORDER.includes(n))];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    try {
      await onAdd(ns, value.trim());
      setValue("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tags">
      {names.map((n) => (
        <div key={n} className="tag-group">
          <span className="tag-ns">{n}</span>
          <div className="chips">
            {groups.get(n)!.map((t) => (
              <span
                key={t.id}
                className={`chip ${t.source}`}
                title={t.source === "auto" ? `auto · ${Math.round((t.confidence ?? 0) * 100)}%` : "manual"}
              >
                {n === "color" && <span className="swatch" style={{ background: t.value }} />}
                {t.value}
                {canEdit && (
                  <button className="chip-x" aria-label={`remove ${t.value}`} onClick={() => void onRemove(t.id)}>
                    ×
                  </button>
                )}
              </span>
            ))}
          </div>
        </div>
      ))}
      {canEdit && (
        <form className="tag-add" onSubmit={submit}>
          <select className="select" value={ns} onChange={(e) => setNs(e.target.value)} aria-label="namespace">
            {ORDER.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="add tag" aria-label="tag value" />
          <button className="btn" disabled={busy || !value.trim()}>Add</button>
        </form>
      )}
    </div>
  );
}
