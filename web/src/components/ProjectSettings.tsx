import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Problem } from "../api";
import type { Project, ProjectRole } from "../types";

export default function ProjectSettings({ project, onClose }: { project: Project; onClose: () => void }) {
  const qc = useQueryClient();
  const access = useQuery({ queryKey: ["access", project.id], queryFn: () => api.listAccess(project.id) });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<ProjectRole>("viewer");
  const [name, setName] = useState(project.name);
  const [phase, setPhase] = useState(project.phase ?? "");
  const [clientLabel, setClientLabel] = useState(project.client_label ?? "");
  const [error, setError] = useState<string | null>(null);

  const invite = useMutation({
    mutationFn: () => api.invite(project.id, email.trim(), role),
    onSuccess: () => {
      setEmail("");
      void qc.invalidateQueries({ queryKey: ["access", project.id] });
    },
    onError: (e) => setError(e instanceof Problem ? e.message : "Invite failed"),
  });
  const revoke = useMutation({
    mutationFn: (userId: string) => api.revoke(project.id, userId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["access", project.id] }),
  });
  const save = useMutation({
    mutationFn: () => api.updateProject(project.id, { name, phase: phase || null, client_label: clientLabel || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["project", project.id] });
      void qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const onInvite = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    invite.mutate();
  };

  return (
    <div className="panel" role="dialog" aria-label="Project settings">
      <div className="panel-head">
        <h2>Project settings</h2>
        <button className="btn ghost" onClick={onClose} aria-label="close">×</button>
      </div>
      <section>
        <h3>Details</h3>
        <label className="field"><span>Name</span><input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="field"><span>Client</span><input value={clientLabel} onChange={(e) => setClientLabel(e.target.value)} placeholder="e.g. Harbour Residences Ltd" /></label>
        <label className="field"><span>Phase</span>
          <select className="select" value={phase} onChange={(e) => setPhase(e.target.value)}>
            <option value="">—</option>
            {["concept", "schematic", "design development", "construction documents", "construction", "completed"].map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <button className="btn primary" onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </section>
      <section>
        <h3>Client access</h3>
        <form className="row" onSubmit={onInvite}>
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="client@example.com" />
          <select className="select" value={role} onChange={(e) => setRole(e.target.value as ProjectRole)}>
            <option value="viewer">viewer</option>
            <option value="editor">editor (can upload)</option>
          </select>
          <button className="btn" disabled={invite.isPending}>Invite</button>
        </form>
        {error && <p className="error">{error}</p>}
        <ul className="access-list">
          {(access.data ?? []).map((a) => (
            <li key={a.user_id}>
              <span>{a.name ?? a.email}</span>
              <span className="pill">{a.role}</span>
              <button className="btn link" onClick={() => revoke.mutate(a.user_id)}>remove</button>
            </li>
          ))}
          {access.data && access.data.length === 0 && <li className="muted">No clients invited yet.</li>}
        </ul>
      </section>
    </div>
  );
}
