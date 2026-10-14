import type { Facets, SearchFilters } from "../types";

const NAMESPACES = ["room", "phase", "style", "material", "color", "object"] as const;
type Ns = (typeof NAMESPACES)[number];

export default function FacetSidebar({
  facets,
  filters,
  onChange,
}: {
  facets: Facets | undefined;
  filters: SearchFilters;
  onChange: (f: SearchFilters) => void;
}) {
  const toggle = (ns: Ns, value: string) => {
    const current = filters[ns] ?? [];
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    onChange({ ...filters, [ns]: next.length ? next : undefined });
  };
  const active = NAMESPACES.some((ns) => (filters[ns]?.length ?? 0) > 0) || filters.kind || filters.favorites_only;
  return (
    <aside className="facets">
      <div className="facet-head">
        <strong>Filter</strong>
        {active && (
          <button className="btn link" onClick={() => onChange({ project_id: filters.project_id })}>
            clear
          </button>
        )}
      </div>
      <div className="facet-group">
        <div className="facet-title">Type</div>
        {(["image", "video"] as const).map((k) => (
          <label key={k} className="facet-row">
            <input
              type="radio"
              name="kind"
              checked={filters.kind === k}
              onChange={() => onChange({ ...filters, kind: filters.kind === k ? null : k })}
              onClick={() => filters.kind === k && onChange({ ...filters, kind: null })}
            />
            <span>{k}</span>
          </label>
        ))}
        <label className="facet-row">
          <input
            type="checkbox"
            checked={!!filters.favorites_only}
            onChange={(e) => onChange({ ...filters, favorites_only: e.target.checked || undefined })}
          />
          <span>★ favorites</span>
        </label>
      </div>
      {NAMESPACES.map((ns) => {
        const values = facets?.[ns];
        if (!values || values.length === 0) return null;
        return (
          <div key={ns} className="facet-group">
            <div className="facet-title">{ns}</div>
            {values.slice(0, 12).map((v) => (
              <label key={v.value} className="facet-row">
                <input type="checkbox" checked={filters[ns]?.includes(v.value) ?? false} onChange={() => toggle(ns, v.value)} />
                {ns === "color" && <span className="swatch" style={{ background: v.value }} />}
                <span className="facet-value">{v.value}</span>
                <span className="muted count">{v.count}</span>
              </label>
            ))}
          </div>
        );
      })}
    </aside>
  );
}
