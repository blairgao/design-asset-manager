import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import AssetCard from "../components/AssetCard";
import FacetSidebar from "../components/FacetSidebar";
import ProjectSettings from "../components/ProjectSettings";
import UploadDropzone from "../components/UploadDropzone";
import type { Asset, SearchFilters, SearchHit } from "../types";

const PAGE = 48;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function ProjectPage() {
  const { id = "" } = useParams();
  const { isStaff, role } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const similarTo = params.get("similar_to");
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 350);
  const [filters, setFilters] = useState<SearchFilters>({ project_id: [id] });
  const [settings, setSettings] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Set<string>>(new Set());

  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.getProject(id) });
  const facets = useQuery({ queryKey: ["facets", id], queryFn: () => api.facets([id]) });
  const boards = useQuery({ queryKey: ["boards", id], queryFn: () => api.listBoards(id), enabled: isStaff || role === "client" });

  useEffect(() => {
    setFilters((f) => ({ ...f, project_id: [id] }));
  }, [id]);
  useEffect(() => {
    const next = new URLSearchParams(params);
    if (dq) next.set("q", dq); else next.delete("q");
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dq]);

  const searchKey = useMemo(() => ["search", id, dq, similarTo, filters] as const, [id, dq, similarTo, filters]);
  const results = useInfiniteQuery({
    queryKey: searchKey,
    queryFn: ({ pageParam }) =>
      api.search({ q: similarTo ? null : dq || null, similar_to: similarTo, filters, limit: PAGE, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

  // Infinite scroll sentinel.
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && results.hasNextPage && !results.isFetchingNextPage) void results.fetchNextPage();
    });
    io.observe(el);
    return () => io.disconnect();
  }, [results]);

  // Poll freshly uploaded assets until they settle, then refresh the grid.
  useEffect(() => {
    if (pending.size === 0) return;
    const t = setInterval(async () => {
      const done: string[] = [];
      for (const aid of pending) {
        try {
          const a = await api.getAsset(aid);
          if (a.status === "ready" || a.status === "failed") done.push(aid);
        } catch {
          done.push(aid);
        }
      }
      if (done.length) {
        setPending((p) => {
          const n = new Set(p);
          done.forEach((d) => n.delete(d));
          return n;
        });
        void qc.invalidateQueries({ queryKey: ["search", id] });
        void qc.invalidateQueries({ queryKey: ["facets", id] });
        void qc.invalidateQueries({ queryKey: ["project", id] });
      }
    }, 3000);
    return () => clearInterval(t);
  }, [pending, qc, id]);

  const onUploaded = useCallback(
    (assetId: string) => {
      setPending((p) => new Set(p).add(assetId));
      void qc.invalidateQueries({ queryKey: ["search", id] });
    },
    [qc, id],
  );

  const addToBoard = useMutation({
    mutationFn: (boardId: string) => api.addBoardAssets(boardId, [...selected]),
    onSuccess: () => {
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: ["boards", id] });
    },
  });

  const hits: SearchHit[] = results.data?.pages.flatMap((p) => p.hits) ?? [];
  const similarAsset = useQuery({ queryKey: ["asset", similarTo], queryFn: () => api.getAsset(similarTo!), enabled: !!similarTo });
  const canUpload = isStaff || role === "client"; // project-level editor check is enforced by the API

  const toggleSelect = (aid: string) =>
    setSelected((s) => {
      const n = new Set(s);
      n.has(aid) ? n.delete(aid) : n.add(aid);
      return n;
    });

  return (
    <div className="page project-page">
      <div className="page-head">
        <div>
          <nav className="crumbs"><Link to="/">Projects</Link> / <span>{project.data?.name ?? "…"}</span></nav>
          <h1>{project.data?.name ?? "Project"}</h1>
          <div className="muted">
            {project.data?.client_label}
            {project.data?.phase && <span className="pill">{project.data.phase}</span>}
          </div>
        </div>
        <div className="row">
          <Link className="btn" to={`/projects/${id}/boards`}>Boards</Link>
          {isStaff && <button className="btn" onClick={() => setSettings(true)}>Settings</button>}
        </div>
      </div>

      {canUpload && <UploadDropzone projectId={id} onUploaded={onUploaded} />}

      <div className="searchbar">
        {similarTo ? (
          <div className="similar-banner">
            <span>Similar to</span>
            {similarAsset.data?.thumb_url && <img src={similarAsset.data.thumb_url} alt="" />}
            <span className="muted">{similarAsset.data?.caption ?? similarAsset.data?.filename ?? "…"}</span>
            <button className="btn link" onClick={() => setParams({}, { replace: true })}>clear</button>
          </div>
        ) : (
          <input
            type="search"
            className="search-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder='Search by meaning, e.g. "warm oak kitchen with black fixtures"'
            aria-label="Search assets"
          />
        )}
        {results.data?.pages[0] && (
          <span className="muted mode">{results.data.pages[0].mode}</span>
        )}
      </div>

      <div className="grid-layout">
        <FacetSidebar facets={facets.data?.facets} filters={filters} onChange={setFilters} />
        <section className="grid-area">
          {selected.size > 0 && (
            <div className="selection-bar">
              <span>{selected.size} selected</span>
              {(boards.data ?? []).length > 0 && (
                <select className="select" defaultValue="" onChange={(e) => e.target.value && addToBoard.mutate(e.target.value)}>
                  <option value="" disabled>Add to board…</option>
                  {boards.data!.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              )}
              <button className="btn link" onClick={() => setSelected(new Set())}>clear</button>
            </div>
          )}
          {results.isLoading && <p className="muted">Loading…</p>}
          {results.error && <p className="error">{String(results.error)}</p>}
          <div className="asset-grid">
            {hits.map((h) => (
              <AssetCard
                key={h.asset.id}
                asset={h.asset as Asset}
                matched={h.matched_tags}
                selected={selected.has(h.asset.id)}
                onToggleSelect={canUpload ? toggleSelect : undefined}
              />
            ))}
          </div>
          {!results.isLoading && hits.length === 0 && (
            <p className="muted empty">{dq || similarTo ? "Nothing matches." : "No assets yet. Upload some above."}</p>
          )}
          <div ref={sentinel} className="sentinel">
            {results.isFetchingNextPage && <span className="muted">Loading more…</span>}
          </div>
        </section>
      </div>

      {settings && project.data && <ProjectSettings project={project.data} onClose={() => setSettings(false)} />}
    </div>
  );
}
