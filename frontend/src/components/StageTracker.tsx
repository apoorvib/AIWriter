import type { PipelineStage, StageStatus } from "../types";

const STATUS_ICON: Record<StageStatus, string> = {
  pending: ".",
  running: "...",
  done: "OK",
  error: "!",
  skipped: "-",
};

interface Props {
  stages: PipelineStage[];
}

export default function StageTracker({ stages }: Props) {
  return (
    <div className="stage-tracker">
      {stages.map((stage, i) => (
        <div key={stage.key} className={`stage-item stage-${stage.status}`}>
          <div className="stage-icon">{STATUS_ICON[stage.status]}</div>
          <div className="stage-label">{stage.label}</div>
          {i < stages.length - 1 && <div className="stage-connector" />}
        </div>
      ))}
    </div>
  );
}
