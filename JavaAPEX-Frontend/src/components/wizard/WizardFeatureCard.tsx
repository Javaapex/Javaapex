import type { CSSProperties, ReactNode } from "react";
import { WizardInfoTooltip } from "./WizardInfoTooltip";

interface WizardFeatureCardProps {
  title: string;
  description: ReactNode;
  iconBadge: ReactNode;
  accent: string;
  detail?: ReactNode;
  tooltipLabel?: string;
  tooltipContent?: ReactNode;
  minHeight?: number;
  progressBar?: boolean;
  containerStyle?: CSSProperties;
}

export function WizardFeatureCard({
  title,
  description,
  iconBadge,
  accent,
  detail,
  tooltipLabel,
  tooltipContent,
  minHeight = 155,
  progressBar = true,
  containerStyle,
}: WizardFeatureCardProps) {
  return (
    <div className="wizard-feature-card" style={{ minHeight, ...containerStyle }}>
      {tooltipContent ? (
        <div style={{ position: "absolute", top: 12, right: 12 }}>
          <WizardInfoTooltip
            label={tooltipLabel ?? `${title} information`}
            triggerClassName="ui-info-trigger ui-info-trigger-light"
            width={320}
            dark={false}
            panelStyle={{ minHeight: 140 }}
          >
            <div
              style={{
                height: "100%",
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "flex-start",
                width: "100%",
              }}
            >
              {tooltipContent}
            </div>
          </WizardInfoTooltip>
        </div>
      ) : null}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 12 }}>
        {iconBadge}
        <div style={{ flex: 1 }}>
          <div className="wizard-select-card-title" style={{ marginBottom: 4 }}>
            {title}
          </div>
          <div className="wizard-select-card-description">{description}</div>
          <div style={{ minHeight: 28, marginTop: 8 }}>
            {detail ? (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  padding: "4px 10px",
                  borderRadius: 999,
                  backgroundColor: `${accent}12`,
                  color: accent,
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {detail}
              </div>
            ) : null}
          </div>
        </div>
      </div>
      {progressBar ? (
        <div
          style={{
            width: "100%",
            height: 4,
            backgroundColor: `${accent}20`,
            borderRadius: 2,
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              height: "100%",
              backgroundColor: accent,
              borderRadius: 2,
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
