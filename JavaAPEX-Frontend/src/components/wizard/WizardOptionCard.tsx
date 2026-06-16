import type { CSSProperties, ReactNode } from "react";
import { buildWizardAccentVars } from "./wizardUi";

interface WizardOptionCardProps {
  accent: string;
  title: string;
  description: ReactNode;
  iconBadge: ReactNode;
  selected?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  topRight?: ReactNode;
  titleAccessory?: ReactNode;
  detail?: ReactNode;
  footer?: ReactNode;
  containerStyle?: CSSProperties;
  titleStyle?: CSSProperties;
  descriptionStyle?: CSSProperties;
  detailStyle?: CSSProperties;
  headerStyle?: CSSProperties;
  bodyStyle?: CSSProperties;
  footerStyle?: CSSProperties;
}

export function WizardOptionCard({
  accent,
  title,
  description,
  iconBadge,
  selected = false,
  disabled = false,
  onClick,
  topRight,
  titleAccessory,
  detail,
  footer,
  containerStyle,
  titleStyle,
  descriptionStyle,
  detailStyle,
  headerStyle,
  bodyStyle,
  footerStyle,
}: WizardOptionCardProps) {
  const cardClassName = `wizard-select-card${selected ? " is-selected" : ""}${disabled ? " is-disabled" : ""}`;

  return (
    <div
      className={cardClassName}
      onClick={onClick}
      style={{
        ...buildWizardAccentVars(accent),
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        ...containerStyle,
      }}
    >
      {topRight}
      <div style={{ flex: footer ? 1 : undefined, ...bodyStyle }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            marginBottom: 12,
            paddingRight: topRight ? 44 : 0,
            ...headerStyle,
          }}
        >
          {iconBadge}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="wizard-select-card-title" style={titleStyle}>
              {title}
            </div>
            {titleAccessory}
          </div>
        </div>
        <div className="wizard-select-card-description" style={descriptionStyle}>
          {description}
        </div>
        {detail ? (
          <div className="wizard-select-card-detail" style={{ marginTop: 10, ...detailStyle }}>
            {detail}
          </div>
        ) : null}
      </div>
      {footer ? <div style={{ marginTop: 16, ...footerStyle }}>{footer}</div> : null}
    </div>
  );
}
