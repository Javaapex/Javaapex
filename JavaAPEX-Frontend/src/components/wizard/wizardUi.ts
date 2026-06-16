import type { CSSProperties } from "react";

const normalizeHex = (value: string): string => {
  const hex = value.trim().replace("#", "");

  if (hex.length === 3) {
    return `#${hex
      .split("")
      .map((char) => `${char}${char}`)
      .join("")}`;
  }

  return hex.length === 6 ? `#${hex}` : value;
};

const clampAlpha = (value: number): number => Math.max(0, Math.min(1, value));

export const withHexAlpha = (value: string, alpha: number): string => {
  const normalized = normalizeHex(value);
  const hex = normalized.replace("#", "");

  if (hex.length !== 6) {
    return normalized;
  }

  const red = Number.parseInt(hex.slice(0, 2), 16);
  const green = Number.parseInt(hex.slice(2, 4), 16);
  const blue = Number.parseInt(hex.slice(4, 6), 16);

  return `rgba(${red}, ${green}, ${blue}, ${clampAlpha(alpha)})`;
};

export const buildWizardAccentVars = (accent: string): CSSProperties =>
  ({
    "--wizard-accent": normalizeHex(accent),
    "--wizard-accent-soft": withHexAlpha(accent, 0.12),
    "--wizard-accent-border": withHexAlpha(accent, 0.2),
    "--wizard-accent-shadow": withHexAlpha(accent, 0.18),
    "--wizard-accent-shadow-strong": withHexAlpha(accent, 0.28),
  }) as CSSProperties;

export const getFrameworkAccent = (frameworkType: string): string => {
  if (frameworkType === "Testing Framework") return "#14b8a6";
  if (frameworkType === "Application Framework") return "#22c55e";
  if (frameworkType === "ORM Framework") return "#0ea5e9";
  if (frameworkType === "Logging") return "#f59e0b";
  if (frameworkType === "Mocking Framework") return "#8b5cf6";
  if (frameworkType === "JSON Processing") return "#2563eb";
  return "#7c3aed";
};

export const getFileAccent = (fileName: string, fileType: string): string => {
  if (fileType === "dir") return "#f59e0b";

  const ext = fileName.split(".").pop()?.toLowerCase();

  switch (ext) {
    case "java":
      return "#ea580c";
    case "xml":
    case "json":
    case "js":
    case "ts":
      return "#2563eb";
    case "yml":
    case "yaml":
    case "properties":
    case "gradle":
      return "#7c3aed";
    case "sql":
      return "#0891b2";
    case "html":
    case "css":
      return "#0f766e";
    case "xlsx":
      return "#16a34a";
    case "png":
      return "#db2777";
    default:
      return "#64748b";
  }
};
