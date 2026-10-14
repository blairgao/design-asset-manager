import { Navigate, Route, Routes } from "react-router-dom";
import { useViewer } from "./viewer";
import Layout from "./components/Layout";
import Projects from "./pages/Projects";
import ProjectPage from "./pages/Project";
import AssetDetail from "./pages/AssetDetail";
import Boards from "./pages/Boards";
import BoardPage from "./pages/Board";

function RequireViewer({ children }: { children: JSX.Element }) {
  const { me, loading, error, firm } = useViewer();
  if (loading) return <div className="center muted">Loading…</div>;
  if (error || !me) return <div className="center error">Could not reach the API. {String(error ?? "")}</div>;
  if (!firm) return <div className="center muted">This user is not a member of any firm yet.</div>;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route
        element={
          <RequireViewer>
            <Layout />
          </RequireViewer>
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
