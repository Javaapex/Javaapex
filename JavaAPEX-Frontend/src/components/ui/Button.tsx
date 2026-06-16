import React from "react";
import "./Button.css";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual variant of the button */
  variant?: ButtonVariant;
  /** Size preset */
  size?: ButtonSize;
  /** Optional icon rendered before the label */
  icon?: React.ReactNode;
  /** Optional icon rendered after the label */
  iconRight?: React.ReactNode;
  /** Show a loading spinner instead of content */
  loading?: boolean;
  /** Stretch to fill parent width */
  fullWidth?: boolean;
}

const Button: React.FC<ButtonProps> = ({
  variant = "primary",
  size = "md",
  icon,
  iconRight,
  loading = false,
  fullWidth = false,
  disabled,
  children,
  className = "",
  ...rest
}) => {
  const classNames = [
    "ui-button",
    `ui-button--${variant}`,
    `ui-button--${size}`,
    fullWidth ? "ui-button--full" : "",
    loading ? "ui-button--loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      className={classNames}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? (
        <span className="ui-button__spinner" />
      ) : (
        <>
          {icon && <span className="ui-button__icon">{icon}</span>}
          {children && <span className="ui-button__label">{children}</span>}
          {iconRight && <span className="ui-button__icon">{iconRight}</span>}
        </>
      )}
    </button>
  );
};

export default Button;
