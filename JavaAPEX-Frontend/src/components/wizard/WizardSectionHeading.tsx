import type { CSSProperties, ReactNode } from "react";

interface WizardSectionHeadingProps {
  title: ReactNode;
  description?: ReactNode;
  style?: CSSProperties;
  titleStyle?: CSSProperties;
  descriptionStyle?: CSSProperties;
}

export function WizardSectionHeading({
  title,
  description,
  style,
  titleStyle,
  descriptionStyle,
}: WizardSectionHeadingProps) {
  return (
    <div style={style}>
      <div
        style={{
          fontSize: 16,
          fontWeight: 600,
          color: "#1e293b",
          marginBottom: description ? 8 : 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
          ...titleStyle,
        }}
      >
        {title}
      </div>
      {description ? (
        <div
          style={{
            fontSize: 14,
            color: "#64748b",
            lineHeight: 1.5,
            ...descriptionStyle,
          }}
        >
          {description}
        </div>
      ) : null}
    </div>
  );
}
