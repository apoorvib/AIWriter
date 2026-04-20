import type { CandidateTopic } from "../types";

interface Props {
  topic: CandidateTopic;
  onSelect: (topicId: string) => void;
  onReject: (topicId: string) => void;
  selected: boolean;
}

function ScoreBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="score-value">{Math.round(value * 100)}</span>
    </div>
  );
}

export default function TopicCard({ topic, onSelect, onReject, selected }: Props) {
  return (
    <div
      className={`topic-card${selected ? " selected" : ""}`}
      onClick={() => onSelect(topic.topic_id)}
    >
      <h3 className="topic-title">{topic.title}</h3>
      <p className="topic-rq"><em>{topic.research_question}</em></p>
      <p className="topic-thesis">{topic.tentative_thesis_direction}</p>
      <p className="topic-rationale">{topic.rationale}</p>
      <div className="scores">
        <ScoreBar value={topic.fit_score} label="Fit" />
        <ScoreBar value={topic.evidence_score} label="Evidence" />
        <ScoreBar value={topic.originality_score} label="Originality" />
      </div>
      <div className="topic-sources">
        {topic.source_leads.map((s) => (
          <span key={s.source_id} className="source-chip">
            {s.source_id} ({s.chunk_count} chunks)
          </span>
        ))}
      </div>
      <div className="topic-actions">
        <button
          type="button"
          className="text-button"
          onClick={(event) => {
            event.stopPropagation();
            onReject(topic.topic_id);
          }}
        >
          Reject direction
        </button>
      </div>
    </div>
  );
}
