import React from "react";
import "./PageHeader.css";

export interface PageHeaderProps {
  /** The icon rendered inside the badge */
  icon: React.ReactNode;
  /** Accent colour passed through to the icon badge */
  accent?: string;
  /** Page title */
  title: string;
  /** Optional subtitle / description */
  subtitle?: string;
  /** Extra content rendered on the right side (e.g. timer, badges) */
  trailing?: React.ReactNode;
  /** Additional CSS class */
  className?: string;
  /** Inline styles */
  style?: React.CSSProperties;
}

const PageHeader: React.FC<PageHeaderProps> = ({
  icon,
  accent = "#2563eb",
  title,
  subtitle,
  trailing,
  className = "",
  style,
}) => {
  const classNames = ["ui-page-header", className].filter(Boolean).join(" ");

  return (
    <div className={classNames} style={style}>
      <span
        className="ui-page-header__badge wizard-icon-badge wizard-icon-badge-xl"
        style={
          {
            "--wizard-accent": accent,
            "--wizard-accent-soft": `${accent}1f`,
            "--wizard-accent-border": `${accent}33`,
            "--wizard-accent-shadow": `${accent}2e`,
            "--wizard-accent-shadow-strong": `${accent}47`,
          } as React.CSSProperties
        }
      >
        {icon}
      </span>

      <div className="ui-page-header__copy">
        <h2 className="ui-page-header__title">{title}</h2>
        {subtitle && <p className="ui-page-header__subtitle">{subtitle}</p>}
      </div>

      {trailing && <div className="ui-page-header__trailing">{trailing}</div>}
    </div>
  );
};

export default PageHeader;
