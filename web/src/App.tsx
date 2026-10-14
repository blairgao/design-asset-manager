import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import Projects from "./pages/Projects";
import ProjectPage from "./pages/Project";
import AssetDetail from "./pages/AssetDetail";
import Boards from "./pages/Boards";
import BoardPage from "./pages/Board";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { me, loading, firm } = useAuth();
  if (loading) return <div className="center muted">Loading…</div>;
  if (!me) return <div className="center muted">Not signed in.</div>;
  if (!firm)
    return (
      <div className="center">
        <p>Your account is not a member of any firm yet. Ask your firm admin for an invite.</p>
      </div>
    );
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Projects />} />
        <Route path="/projects/:id" element={<ProjectPage />} />
        <Route path="/projects/:id/boards" element={<Boards />} />
        <Route path="/boards/:id" element={<BoardPage />} />
        <Route path="/assets/:id" element={<AssetDetail />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
