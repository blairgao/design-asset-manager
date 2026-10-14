import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useViewer } from "../viewer";

export default function Projects() {
  const { firm, isStaff } = useViewer();
  const qc = useQueryClient();
  const firmId = firm!.firm_id;
  const projects = useQuery({ queryKey: ["projects", firmId], queryFn: () => api.listProjects(firmId) });
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const create = useMutation({
    mutationFn: () => api.createProject(firmId, { name: name.trim(), client_label: client.trim() || null }),
    onSuccess: () => {
      setName("");
      setClient("");
      void qc.invalidateQueries({ queryKey: ["projects", firmId] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate();
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Projects</h1>
      </div>
      {isStaff && (
        <form className="row card inline-form" onSubmit={submit}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New project name" required />
          <input value={client} onChange={(e) => setClient(e.target.value)} placeholder="Client (optional)" />
          <button className="btn primary" disabled={create.isPending || !name.trim()}>Create</button>
        </form>
      )}
      {projects.isLoading && <p className="muted">Loading…</p>}
      {projects.error && <p className="error">{String(projects.error)}</p>}
      <div className="project-grid">
        {(projects.data ?? []).map((p) => (
          <Link key={p.id} to={`/projects/${p.id}`} className="card project-card">
            <div className="project-name">{p.name}</div>
            <div className="muted">{p.client_label ?? "—"}</div>
            <div className="project-foot">
              {p.phase && <span className="pill">{p.phase}</span>}
              <span className="muted">{p.asset_count} assets</span>
            </div>
          </Link>
        ))}
        {projects.data && projects.data.length === 0 && (
          <p className="muted">No projects yet{isStaff ? ". Create one above." : "."}</p>
        )}
      </div>
    </div>
  );
}
