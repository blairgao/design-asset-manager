import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, Problem } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const { me, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && me) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.requestMagicLink(email.trim());
      setSent(true);
    } catch (err) {
      setError(err instanceof Problem ? err.message : "Could not send link");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h1>Sign in</h1>
        <p className="muted">We will email you a one-time link. No password needed.</p>
        {sent ? (
          <p className="notice">If that address is registered, a sign-in link is on its way. Check your inbox.</p>
        ) : (
          <>
            <label className="field">
              <span>Email</span>
              <input
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@firm.com"
              />
            </label>
            {error && <p className="error">{error}</p>}
            <button className="btn primary" disabled={busy || !email}>
              {busy ? "Sending…" : "Email me a link"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
