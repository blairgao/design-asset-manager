import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useViewer } from "../viewer";

export default function Boards() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { isStaff } = useViewer();
  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.getProject(id) });
  const boards = useQuery({ queryKey: ["boards", id], queryFn: () => api.listBoards(id) });
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.createBoard(id, name.trim()),
    onSuccess: () => {
      setName("");
      void qc.invalidateQueries({ queryKey: ["boards", id] });
    },
  });
  const share = useMutation({
    mutationFn: ({ boardId, shared }: { boardId: string; shared: boolean }) => api.updateBoard(boardId, { shared_with_clients: shared }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["boards", id] }),
  });

  return (
    <div className="page">
      <nav className="crumbs"><Link to="/">Projects</Link> / <Link to={`/projects/${id}`}>{project.data?.name ?? "…"}</Link> / <span>Boards</span></nav>
      <div className="page-head"><h1>Boards</h1></div>
      <form
        className="row card inline-form"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
      >
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New board name" />
        <button className="btn primary" disabled={!name.trim() || create.isPending}>Create</button>
      </form>
      <div className="project-grid">
        {(boards.data ?? []).map((b) => (
          <div key={b.id} className="card board-card">
            <Link to={`/boards/${b.id}`} className="board-cover">
              {b.cover_url ? <img src={b.cover_url} alt="" /> : <div className="thumb-placeholder">◫</div>}
            </Link>
            <div className="project-name"><Link to={`/boards/${b.id}`}>{b.name}</Link></div>
            <div className="project-foot">
              <span className="muted">{b.asset_count} assets</span>
              {isStaff && (
                <label className="facet-row">
                  <input type="checkbox" checked={b.shared_with_clients} onChange={(e) => share.mutate({ boardId: b.id, shared: e.target.checked })} />
                  <span>shared with clients</span>
                </label>
              )}
            </div>
          </div>
        ))}
        {boards.data && boards.data.length === 0 && <p className="muted">No boards yet.</p>}
      </div>
    </div>
  );
}
