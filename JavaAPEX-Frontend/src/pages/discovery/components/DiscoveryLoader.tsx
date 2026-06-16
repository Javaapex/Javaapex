import { FaCogs, FaProjectDiagram, FaSearch, FaStream } from "react-icons/fa";

interface DiscoveryLoaderProps {
  title?: string;
  subtitle?: string;
  elapsedLabel?: string | null;
  elapsedSeconds?: number;
  compact?: boolean;
}

const DISCOVERY_STAGES = [
  {
    label: "Repository Map",
    icon: <FaSearch />,
    detail: "Scanning folders, modules, and build signals",
  },
  {
    label: "Dependency Graph",
    icon: <FaCogs />,
    detail: "Reading libraries, frameworks, and risk markers",
  },
  {
    label: "Preview Signals",
    icon: <FaStream />,
    detail: "Preparing previews and migration-oriented hints",
  },
  {
    label: "Service Fit",
    icon: <FaProjectDiagram />,
    detail: "Estimating architecture and microservice readiness",
  },
];

export function DiscoveryLoader({
  title = "Analyzing your repository",
  subtitle = "Building structure, preview, dependencies, and migration signals for the next step.",
  elapsedLabel,
  elapsedSeconds = 0,
  compact = false,
}: DiscoveryLoaderProps) {
  const stageDurationSeconds = 4;
  const boundedElapsedSeconds = Math.max(0, elapsedSeconds);
  const rawStageIndex = Math.floor(boundedElapsedSeconds / stageDurationSeconds);
  const activeStageIndex = Math.min(DISCOVERY_STAGES.length - 1, rawStageIndex);
  const stageProgress = (boundedElapsedSeconds % stageDurationSeconds) / stageDurationSeconds;
  const currentStage = DISCOVERY_STAGES[activeStageIndex];
  const progressPercent =
    activeStageIndex >= DISCOVERY_STAGES.length - 1
      ? Math.min(94, 78 + Math.min(16, boundedElapsedSeconds - stageDurationSeconds * (DISCOVERY_STAGES.length - 1)))
      : ((activeStageIndex + stageProgress) / DISCOVERY_STAGES.length) * 100;

  return (
    <div className={`discovery-loader${compact ? " is-compact" : ""}`}>
      <div className="discovery-loader-visual" aria-hidden="true">
        <div className="discovery-loader-orbit" />
        <div className="discovery-loader-core">
          {currentStage.icon}
        </div>
        <span className="discovery-loader-node is-one" />
        <span className="discovery-loader-node is-two" />
        <span className="discovery-loader-node is-three" />
      </div>

      <div className="discovery-loader-content">
        <div className="discovery-loader-eyebrow">
          Repository Intelligence Engine
          {elapsedLabel ? <span className="discovery-loader-timer">{elapsedLabel}</span> : null}
        </div>
        <div className="discovery-loader-title">{title}</div>
        <div className="discovery-loader-subtitle">{subtitle}</div>
        <div className="discovery-loader-current-step">
          <span className="discovery-loader-current-label">Now:</span>
          <span>{currentStage.detail}</span>
        </div>

        <div className="discovery-loader-stage-grid">
          {DISCOVERY_STAGES.map((stage, index) => (
            <div
              key={stage.label}
              className={`discovery-loader-stage${index < activeStageIndex ? " is-complete" : ""}${index === activeStageIndex ? " is-active" : ""}`}
            >
              <span className="discovery-loader-stage-icon">{stage.icon}</span>
              <span className="discovery-loader-stage-text">
                <span className="discovery-loader-stage-title">{stage.label}</span>
                <span className="discovery-loader-stage-meta">
                  {index < activeStageIndex ? "Complete" : index === activeStageIndex ? "In progress" : "Queued"}
                </span>
              </span>
            </div>
          ))}
        </div>

        <div className="discovery-loader-progress" aria-hidden="true">
          <div className="discovery-loader-progress-bar" style={{ width: `${progressPercent}%` }} />
        </div>
      </div>
    </div>
  );
}
