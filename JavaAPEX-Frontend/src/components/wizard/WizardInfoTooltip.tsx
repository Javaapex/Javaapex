import type { CSSProperties, ReactNode } from "react";

interface WizardInfoTooltipProps {
  label: string;
  children: ReactNode;
  width?: number;
  placement?: "left" | "right";
  dark?: boolean;
  triggerClassName?: string;
  triggerStyle?: CSSProperties;
  panelStyle?: CSSProperties;
}

export function WizardInfoTooltip({
  label,
  children,
  width = 280,
  placement = "right",
  dark = true,
  triggerClassName = "ui-info-trigger",
  triggerStyle,
  panelStyle,
}: WizardInfoTooltipProps) {
  const panelBaseStyle: CSSProperties = dark
    ? {
        backgroundColor: "#1e293b",
        color: "#f1f5f9",
        boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
      }
    : {
        background: "#fff",
        color: "#0f172a",
        border: "1px solid #e2e8f0",
        boxShadow: "0 12px 30px rgba(15, 23, 42, 0.12)",
      };

  const arrowStyle: CSSProperties =
    placement === "left"
      ? {
          left: 9,
          borderBottom: dark ? "6px solid #1e293b" : "6px solid #fff",
        }
      : {
          right: 16,
          borderBottom: dark ? "6px solid #1e293b" : "6px solid #fff",
        };

  return (
    <div className="ui-info-tooltip-host" style={{ position: "relative", display: "inline-flex" }}>
      <button
        type="button"
        aria-label={label}
        className={triggerClassName}
        style={{ padding: 0, ...triggerStyle }}
      >
        i
      </button>
      <div
        className="ui-info-tooltip"
        style={{
          position: "absolute",
          top: 28,
          width,
          zIndex: 1000,
          padding: dark ? "12px 16px" : "14px 18px",
          borderRadius: dark ? 8 : 10,
          fontSize: 12,
          lineHeight: 1.5,
          whiteSpace: "normal",
          ...(placement === "left" ? { left: 0 } : { right: 0 }),
          ...panelBaseStyle,
          ...panelStyle,
        }}
      >
        {children}
        <div
          style={{
            position: "absolute",
            top: -6,
            width: 0,
            height: 0,
            borderLeft: "6px solid transparent",
            borderRight: "6px solid transparent",
            ...arrowStyle,
          }}
        />
      </div>
    </div>
  );
}
