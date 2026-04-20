import { BrowserRouter, Routes, Route } from "react-router-dom";
import NewJob from "./pages/NewJob";
import TopicSelection from "./pages/TopicSelection";
import PipelineView from "./pages/PipelineView";
import "./styles.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<NewJob />} />
        <Route path="/jobs/:jobId/topics" element={<TopicSelection />} />
        <Route path="/jobs/:jobId/pipeline" element={<PipelineView />} />
      </Routes>
    </BrowserRouter>
  );
}
