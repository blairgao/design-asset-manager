import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useViewer } from "../viewer";
import AssetCard from "../components/AssetCard";

export default function BoardPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { isStaff, me } = useViewer();
  const board = useQuery({ queryKey: ["board", id], queryFn: () => api.getBoard(id) });
  const assets = useQuery({ queryKey: ["board-assets", id], queryFn: () => api.boardAssets(id) });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [name, setName] = useState<string | null>(null);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["board", id] });
    void qc.invalidateQueries({ queryKey: ["board-assets", id] });
    void qc.invalidateQueries({ queryKey: ["boards"] });
  };
  const removeSelected = useMutation({
    mutationFn: () => api.setBoardAssets(id, (assets.data ?? []).map((a) => a.id).filter((a) => !selected.has(a))),
    onSuccess: () => {
      setSelected(new Set());
      refresh();
    },
  });
  const rename = useMutation({
    mutationFn: () => api.updateBoard(id, { name: name ?? "" }),
    onSuccess: () => {
      setName(null);
      refresh();
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteBoard(id),
    onSuccess: () => navigate(`/projects/${board.data?.project_id}/boards`),
  });

  const canEdit = isStaff || board.data?.created_by === me?.id;
  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/">Projects</Link> / <Link to={`/projects/${board.data?.project_id}`}>project</Link> /{" "}
        <Link to={`/projects/${board.data?.project_id}/boards`}>Boards</Link> / <span>{board.data?.name ?? "…"}</span>
      </nav>
      <div className="page-head">
        {name === null ? (
          <h1>
            {board.data?.name ?? "Board"}{" "}
            {canEdit && <button className="btn link" onClick={() => setName(board.data?.name ?? "")}>rename</button>}
          </h1>
        ) : (
          <div className="row">
            <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            <button className="btn primary" onClick={() => rename.mutate()}>Save</button>
            <button className="btn ghost" onClick={() => setName(null)}>Cancel</button>
          </div>
        )}
        <div className="row">
          {board.data?.shared_with_clients && <span className="pill">shared with clients</span>}
          {canEdit && <button className="btn danger" onClick={() => window.confirm("Delete this board?") && del.mutate()}>Delete board</button>}
        </div>
      </div>
      {selected.size > 0 && (
        <div className="selection-bar">
          <span>{selected.size} selected</span>
          <button className="btn" onClick={() => removeSelected.mutate()}>Remove from board</button>
          <button className="btn link" onClick={() => setSelected(new Set())}>clear</button>
        </div>
      )}
      <div className="asset-grid">
        {(assets.data ?? []).map((a) => (
          <AssetCard
            key={a.id}
            asset={a}
            selected={selected.has(a.id)}
            onToggleSelect={
              canEdit
                ? (aid) =>
                    setSelected((s) => {
                      const n = new Set(s);
                      n.has(aid) ? n.delete(aid) : n.add(aid);
                      return n;
                    })
                : undefined
            }
          />
        ))}
      </div>
      {assets.data && assets.data.length === 0 && (
        <p className="muted empty">Empty board. Select assets in the project grid and choose “Add to board”.</p>
      )}
    </div>
  );
}
