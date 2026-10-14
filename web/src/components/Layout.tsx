import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout() {
  const { me, firm, switchFirm, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden>▣</span> Asset Library
        </Link>
        <div className="topbar-right">
          {me && me.memberships.length > 1 ? (
            <select
              className="select"
              value={firm?.firm_id ?? ""}
              onChange={(e) => {
                switchFirm(e.target.value);
                navigate("/");
              }}
              aria-label="Active firm"
            >
              {me.memberships.map((m) => (
                <option key={m.firm_id} value={m.firm_id}>
                  {m.firm_name}
                </option>
              ))}
            </select>
          ) : (
            <span className="muted">{firm?.firm_name}</span>
          )}
          <span className="pill">{firm?.role}</span>
          <button className="btn ghost" onClick={() => void logout().then(() => navigate("/login"))}>
            Sign out
          </button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
