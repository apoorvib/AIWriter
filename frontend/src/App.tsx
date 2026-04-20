import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import NewJob from "./pages/NewJob";
import TopicSelection from "./pages/TopicSelection";
import PipelineView from "./pages/PipelineView";
import Settings from "./pages/Settings";
import "./styles.css";

export default function App() {
  return (
    <BrowserRouter>
      <nav className="app-nav">
        <NavLink to="/" end className={({ isActive }) => isActive ? "nav-link nav-link-active" : "nav-link"}>
          New job
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => isActive ? "nav-link nav-link-active" : "nav-link"}>
          Settings
        </NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<NewJob />} />
        <Route path="/jobs/:jobId/topics" element={<TopicSelection />} />
        <Route path="/jobs/:jobId/pipeline" element={<PipelineView />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </BrowserRouter>
  );
}
