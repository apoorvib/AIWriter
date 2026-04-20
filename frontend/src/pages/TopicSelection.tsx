import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import TopicCard from "../components/TopicCard";
import { generateTopics, rejectTopic, selectTopic } from "../api";
import type { CandidateTopic } from "../types";

export default function TopicSelection() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();

  const [candidates, setCandidates] = useState<CandidateTopic[]>([]);
  const [roundNumber, setRoundNumber] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [instruction, setInstruction] = useState("");
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockingQuestions, setBlockingQuestions] = useState<string[]>([]);

  async function fetchTopics(userInstruction?: string) {
    if (!jobId) return;
    setLoading(true);
    setError(null);
    setSelectedId(null);
    try {
      const result = await generateTopics(jobId, userInstruction);
      setCandidates(result.candidates);
      setRoundNumber(result.round_number);
      setBlockingQuestions(result.blocking_questions);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate topics.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchTopics();
  }, [jobId]);

  async function handleSelect() {
    if (!jobId || !selectedId) return;
    setSelecting(true);
    setError(null);
    try {
      await selectTopic(jobId, selectedId, roundNumber);
      navigate(`/jobs/${jobId}/pipeline`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to select topic.");
      setSelecting(false);
    }
  }

  async function handleReject() {
    if (!jobId || !rejectingId) return;
    if (!rejectReason.trim()) {
      setError("Add a short reason so the next round can avoid that direction.");
      return;
    }
    setRejecting(true);
    setError(null);
    try {
      await rejectTopic(jobId, rejectingId, roundNumber, rejectReason.trim());
      setRejectingId(null);
      setRejectReason("");
      await fetchTopics(instruction || "Avoid the rejected direction.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reject topic.");
    } finally {
      setRejecting(false);
    }
  }

  return (
    <div className="page page-wide">
      <header className="page-header">
        <p className="eyebrow">Job {jobId}</p>
        <h1>Choose the best direction</h1>
        <p className="subtitle">Select a topic or reject a direction before generating another round.</p>
      </header>

      {blockingQuestions.length > 0 && (
        <div className="blocking-questions">
          <strong>Unresolved assignment questions:</strong>
          <ul>{blockingQuestions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </div>
      )}

      {loading ? (
        <div className="loading-state">
          <div className="spinner-large" />
          <p>Generating topic candidates...</p>
        </div>
      ) : (
        <>
          <div className="topic-grid">
            {candidates.map((c) => (
              <TopicCard
                key={c.topic_id}
                topic={c}
                selected={selectedId === c.topic_id}
                onSelect={setSelectedId}
                onReject={setRejectingId}
              />
            ))}
          </div>

          {rejectingId && (
            <div className="reject-panel">
              <div>
                <strong>Reject this direction</strong>
                <p>Use a concrete reason. It is passed into the next topic round.</p>
              </div>
              <input
                className="instruction-input"
                placeholder="Example: too broad, not enough source evidence, wrong angle"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
              />
              <div className="button-row">
                <button className="btn-secondary" type="button" onClick={() => setRejectingId(null)}>
                  Cancel
                </button>
                <button className="btn-primary" type="button" onClick={handleReject} disabled={rejecting}>
                  {rejecting ? "Rejecting..." : "Reject and regenerate"}
                </button>
              </div>
            </div>
          )}

          <div className="regenerate-row">
            <input
              className="instruction-input"
              placeholder="Optional direction for the next round"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
            />
            <button className="btn-secondary" onClick={() => fetchTopics(instruction || undefined)}>
              Regenerate
            </button>
          </div>

          {error && <p className="error-text">{error}</p>}

          <button className="btn-primary" disabled={!selectedId || selecting} onClick={handleSelect}>
            {selecting ? "Selecting..." : "Use selected topic"}
          </button>
        </>
      )}
    </div>
  );
}
