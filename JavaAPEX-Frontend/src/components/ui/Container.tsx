import React from "react";
import "./Container.css";

export type ContainerSize = "sm" | "md" | "lg" | "xl" | "full";

export interface ContainerProps {
  /** Maximum width preset */
  size?: ContainerSize;
  /** Center the container horizontally */
  centered?: boolean;
  /** Add vertical padding */
  padded?: boolean;
  /** Additional CSS class */
  className?: string;
  /** Inline styles */
  style?: React.CSSProperties;
  /** Container content */
  children?: React.ReactNode;
}

const Container: React.FC<ContainerProps> = ({
  size = "full",
  centered = false,
  padded = true,
  className = "",
  style,
  children,
}) => {
  const classNames = [
    "ui-container",
    `ui-container--${size}`,
    centered ? "ui-container--centered" : "",
    padded ? "ui-container--padded" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classNames} style={style}>
      {children}
    </div>
  );
};

export default Container;
