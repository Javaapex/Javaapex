import React from "react";
import "./Card.css";

export type CardVariant = "default" | "elevated" | "outlined" | "glass";

export interface CardProps {
  /** Visual variant of the card */
  variant?: CardVariant;
  /** Optional header content (title area) */
  header?: React.ReactNode;
  /** Optional footer content */
  footer?: React.ReactNode;
  /** Remove default padding */
  noPadding?: boolean;
  /** Additional CSS class */
  className?: string;
  /** Inline styles */
  style?: React.CSSProperties;
  /** Card body content */
  children?: React.ReactNode;
}

const Card: React.FC<CardProps> = ({
  variant = "default",
  header,
  footer,
  noPadding = false,
  className = "",
  style,
  children,
}) => {
  const classNames = [
    "ui-card",
    `ui-card--${variant}`,
    noPadding ? "ui-card--no-padding" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classNames} style={style}>
      {header && <div className="ui-card__header">{header}</div>}
      <div className="ui-card__body">{children}</div>
      {footer && <div className="ui-card__footer">{footer}</div>}
    </div>
  );
};

export default Card;
