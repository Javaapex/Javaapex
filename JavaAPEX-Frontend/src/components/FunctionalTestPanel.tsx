import React from "react";
import { FaFileAlt } from "react-icons/fa";
import type { FunctionalTestScopePreview } from "../services/api";

export interface FunctionalToolView {
  id: string;
  name: string;
  description: string;
  reason: string;
  confidence: number;
  color: string;
  tag: string;
  active: boolean;
}

interface FunctionalTestPanelProps {
  tools: FunctionalToolView[];
  /**
   * Explicitly selected tool ids. An EMPTY array means "auto" — the panel then
   * highlights whatever the analyzer marked as recommended/active. A non-empty
   * array is the user's custom multi-tool selection.
   */
  selectedToolIds: string[];
  onToggleTool: (id: string) => void;
  onResetAuto: () => void;
  preview: FunctionalTestScopePreview | null;
  loading: boolean;
  error: string | null;
  onDownloadUi: () => void;
  onDownloadApi: () => void;
}

const TOOL_EMOJI: Record<string, string> = {
  PLAYWRIGHT: "🎭",
  REST_ASSURED: "🔗",
  MOCK_MVC: "🌱",
  SELENIUM: "🌐",
  SCHEMATHESIS: "📋",
};

const METHOD_COLORS: Record<string, string> = {
  GET: "#2563eb",
  POST: "#16a34a",
  PUT: "#f59e0b",
  PATCH: "#8b5cf6",
  DELETE: "#ef4444",
};

function methodColor(method: string): string {
  return METHOD_COLORS[(method || "").toUpperCase()] || "#64748b";
}

export default function FunctionalTestPanel({
  tools,
  selectedToolIds,
  onToggleTool,
  onResetAuto,
  preview,
  loading,
  error,
  onDownloadUi,
  onDownloadApi,
}: FunctionalTestPanelProps) {
  const [hoveredToolId, setHoveredToolId] = React.useState<string | null>(null);

  const counts = preview?.existingTestFileCounts;
  const existingTotal =
    preview?.existingTestFilesTotal ??
    (counts ? counts.junit + counts.mockMvc + counts.testFramework + counts.e2e : 0);
  const functionalFiles = preview?.existingTestFiles ?? [];
  const uiTestCases = preview?.uiTestCases ?? [];
  const apiTestCases = preview?.apiTestCases ?? [];

  // "auto" mode = no explicit selection. In that mode a tool is highlighted when
  // the analyzer marked it recommended/active; otherwise only the tools the user
  // explicitly picked are highlighted. Multiple tools can be selected at once.
  const isAutoMode = selectedToolIds.length === 0;
  const isToolSelected = (tool: FunctionalToolView): boolean =>
    isAutoMode ? tool.active : selectedToolIds.includes(tool.id);

  // Map detected existing-test categories to the tool that would otherwise generate them.
  // Modern E2E / spec files map to Playwright; Spring MockMvc tests map to MockMvc.
  // Selenium has no generic fingerprint, so it is never auto-flagged.
  const toolHasExistingTests = (id: string): boolean => {
    if (!counts) return false;
    if (id === "MOCK_MVC") return counts.mockMvc > 0;
    if (id === "PLAYWRIGHT") return counts.e2e > 0 || counts.testFramework > 0;
    return false;
  };

  const cautionTools = tools
    .filter((t) => isToolSelected(t) && toolHasExistingTests(t.id))
    .map((t) => t.id);

  const countBadges = counts
    ? [
        { label: "JUnit", count: counts.junit, kind: "UNIT", color: "#7c3aed", icon: "🧪" },
        { label: "Test Framework", count: counts.testFramework, kind: "E2E", color: "#16a34a", icon: "🧪" },
        { label: "E2E", count: counts.e2e, kind: "E2E", color: "#2563eb", icon: "📁" },
        { label: "MockMvc", count: counts.mockMvc, kind: "UNIT", color: "#16a34a", icon: "🌱" },
      ].filter((b) => b.count > 0)
    : [];

  return (
    <div>
      {/* ── Existing Test Files count badges ─────────────────── */}
      {/* Always render this section (even when 0) so reviewers can see that the
          repository was scanned — hiding it entirely made it look broken. */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: 16 }}>🧪</span>
          <span style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>
            Existing Test Files ({existingTotal})
          </span>
        </div>
        {existingTotal > 0 && countBadges.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {countBadges.map((b) => (
              <div
                key={b.label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 14px",
                  borderRadius: 10,
                  border: "1px solid #e2e8f0",
                  background: "#fff",
                  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                }}
              >
                <span style={{ fontSize: 14 }}>{b.icon}</span>
                <span style={{ fontWeight: 800, fontSize: 15, color: b.color }}>{b.count}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: "#334155" }}>{b.label}</span>
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                    padding: "2px 7px",
                    borderRadius: 5,
                    background: b.kind === "E2E" ? "#dbeafe" : "#f1f5f9",
                    color: b.kind === "E2E" ? "#2563eb" : "#64748b",
                  }}
                >
                  {b.kind}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "12px 16px",
              borderRadius: 10,
              border: "1px dashed #cbd5e1",
              background: "#f8fafc",
              color: "#475569",
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <span style={{ fontSize: 15 }}>ℹ️</span>
            <span>
              No existing automated test files were detected in this repository — the suite
              below will be generated from scratch.
            </span>
          </div>
        )}
      </div>

      {/* ── Tool selection header + multi-select hint ────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16 }}>🛠️</span>
          <span style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>
            Functional Test Tools
          </span>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: isAutoMode ? "#2563eb" : "#16a34a",
              background: isAutoMode ? "#dbeafe" : "#dcfce7",
              borderRadius: 6,
              padding: "2px 8px",
            }}
          >
            {isAutoMode
              ? "Auto recommendation"
              : `${selectedToolIds.length} selected`}
          </span>
        </div>
        <span style={{ fontSize: 12, color: "#64748b", fontWeight: 500 }}>
          Select one or more tools to validate with — all chosen tools run.
        </span>
      </div>

      {/* ── Tool selection cards ─────────────────────────────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 16,
        }}
      >
        {tools.map((tool) => {
          const selected = isToolSelected(tool);
          const isActive = tool.active;
          const hovered = hoveredToolId === tool.id;
          const emoji = TOOL_EMOJI[tool.id] || "🧩";
          const hasExisting = toolHasExistingTests(tool.id);

          return (
            <div
              key={tool.id}
              onMouseEnter={() => isActive && setHoveredToolId(tool.id)}
              onMouseLeave={() => setHoveredToolId(null)}
              style={{
                background: "#fff",
                borderRadius: 14,
                border: `2px solid ${selected ? "#2563eb" : hovered ? "#93c5fd" : "#e2e8f0"}`,
                padding: "22px 18px 18px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                textAlign: "center",
                opacity: isActive ? 1 : 0.55,
                transition: "all 0.2s ease",
                boxShadow: selected ? "0 4px 16px rgba(37,99,235,0.12)" : "0 1px 3px rgba(0,0,0,0.05)",
              }}
            >
              <div
                style={{
                  width: 52,
                  height: 52,
                  borderRadius: 14,
                  background: "#eff6ff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: 14,
                  fontSize: 24,
                }}
              >
                {emoji}
              </div>
              <h4 style={{ fontWeight: 800, fontSize: 16, color: "#0f172a", marginBottom: 8 }}>
                {tool.name}
              </h4>
              <p style={{ fontSize: 12, color: "#64748b", lineHeight: 1.5, marginBottom: 14, minHeight: 36 }}>
                {tool.description}
              </p>

              <div
                style={{
                  width: "100%",
                  background: "#eff6ff",
                  border: "1px solid #bfdbfe",
                  borderRadius: 10,
                  padding: "10px 12px",
                  marginBottom: 12,
                  textAlign: "left",
                }}
              >
                <p style={{ fontSize: 11, color: "#1e40af", lineHeight: 1.5, margin: 0 }}>{tool.reason}</p>
              </div>

              {hasExisting && (
                <div
                  style={{
                    width: "100%",
                    background: "#fffbeb",
                    border: "1px solid #fde68a",
                    borderRadius: 8,
                    padding: "7px 10px",
                    marginBottom: 12,
                    fontSize: 11,
                    color: "#92400e",
                    fontWeight: 600,
                  }}
                >
                  ⚠️ Test files already exist — only validation will run
                </div>
              )}

              <button
                disabled={!isActive}
                onClick={() => isActive && onToggleTool(tool.id)}
                style={{
                  marginTop: "auto",
                  width: "100%",
                  padding: "11px 0",
                  borderRadius: 9,
                  fontWeight: 700,
                  fontSize: 13,
                  border: selected ? "none" : "1.5px solid #cbd5e1",
                  background: selected ? "#16a34a" : "#fff",
                  color: selected ? "#fff" : "#475569",
                  cursor: isActive ? "pointer" : "not-allowed",
                  transition: "all 0.2s ease",
                }}
              >
                {selected ? "✓ Selected" : "Select"}
              </button>
            </div>
          );
        })}
      </div>

      {/* ── Reset to Auto Recommendation ─────────────────────── */}
      {!isAutoMode && (
        <div style={{ textAlign: "center", marginTop: 16 }}>
          <button
            onClick={onResetAuto}
            style={{
              background: "none",
              border: "none",
              color: "#3b82f6",
              fontSize: 13,
              fontWeight: 700,
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            Reset to Auto Recommendation
          </button>
        </div>
      )}

      {/* ── Caution banner for tools with existing test files ── */}
      {cautionTools.length > 0 && (
        <div
          style={{
            marginTop: 18,
            background: "#fffbeb",
            border: "1px solid #fde68a",
            borderRadius: 10,
            padding: "12px 16px",
            fontSize: 12.5,
            color: "#92400e",
            lineHeight: 1.6,
          }}
        >
          <strong>⚠️ Caution:</strong> The following selected tool(s) already have existing test files in the
          project. Test generation will be skipped and only file validation will be performed:{" "}
          <strong>{cautionTools.join(", ")}</strong>.
        </div>
      )}

      {/* ── Existing Functional Test Files list ──────────────── */}
      <div
        style={{
          marginTop: 24,
          background: "#fff",
          borderRadius: 14,
          border: "1px solid #e2e8f0",
          padding: "20px 22px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <span style={{ fontSize: 16 }}>📋</span>
          <span style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>
            Existing Functional Test Files ({functionalFiles.length})
          </span>
        </div>
        {functionalFiles.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 280, overflowY: "auto" }}>
            {functionalFiles.map((f, idx) => {
              const isE2E = f.label === "E2E";
              return (
                <div
                  key={`${f.path}-${idx}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 14px",
                    borderRadius: 8,
                    background: "#f8fafc",
                    border: "1px solid #f1f5f9",
                  }}
                >
                  <span style={{ fontSize: 14 }}>{isE2E ? "📁" : "🧪"}</span>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                      padding: "3px 9px",
                      borderRadius: 5,
                      background: isE2E ? "#dbeafe" : "#ede9fe",
                      color: isE2E ? "#2563eb" : "#7c3aed",
                      flexShrink: 0,
                    }}
                  >
                    {isE2E ? "E2E" : "Test Framework"}
                  </span>
                  <code
                    style={{
                      fontSize: 12,
                      color: "#334155",
                      fontFamily: "'JetBrains Mono', Menlo, monospace",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {f.path}
                  </code>
                </div>
              );
            })}
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "12px 14px",
              borderRadius: 8,
              background: "#f8fafc",
              border: "1px dashed #cbd5e1",
              color: "#475569",
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <span style={{ fontSize: 15 }}>ℹ️</span>
            <span>
              No existing functional / E2E test files were found in this repository.
            </span>
          </div>
        )}
      </div>

      {/* ── Functional Test Scope Documents ──────────────────── */}
      <div
        style={{
          marginTop: 24,
          background: "#fff",
          borderRadius: 14,
          border: "1px solid #e2e8f0",
          padding: "20px 24px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <FaFileAlt style={{ fontSize: 16, color: "#0f172a" }} />
          <span style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>Functional Test Scope Documents</span>
        </div>
        <p style={{ fontSize: 12, color: "#64748b", lineHeight: 1.6, marginBottom: 16 }}>
          Download a business-friendly overview of the test cases that will be generated and validated for your
          project. These documents describe the scope in clear business language for stakeholder review.
        </p>

        {loading && !preview && (
          <div style={{ padding: "24px 0", textAlign: "center", color: "#64748b", fontSize: 13 }}>
            ⏳ Analyzing project and generating test scope…
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* ── UI Test Cases ── */}
          <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, overflow: "hidden" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "12px 16px",
                background: "#f8fafc",
                borderBottom: "1px solid #e2e8f0",
              }}
            >
              <span style={{ fontWeight: 700, fontSize: 13.5, color: "#0f172a" }}>🖥️ UI Test Cases</span>
              <button
                onClick={onDownloadUi}
                disabled={loading}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "6px 12px",
                  borderRadius: 7,
                  border: "none",
                  background: "#2563eb",
                  color: "#fff",
                  fontSize: 11.5,
                  fontWeight: 700,
                  cursor: loading ? "not-allowed" : "pointer",
                  opacity: loading ? 0.6 : 1,
                }}
              >
                ⬇ Download
              </button>
            </div>
            <div style={{ maxHeight: 360, overflowY: "auto" }}>
              {uiTestCases.length === 0 && (
                <div style={{ padding: "18px 16px", fontSize: 12, color: "#94a3b8" }}>
                  No UI routes detected for this project.
                </div>
              )}
              {uiTestCases.map((tc, idx) => (
                <div
                  key={`ui-${idx}`}
                  style={{
                    padding: "14px 16px",
                    borderBottom: idx === uiTestCases.length - 1 ? "none" : "1px solid #f1f5f9",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8" }}>#{idx + 1}</span>
                    <code
                      style={{
                        fontSize: 12,
                        background: "#f1f5f9",
                        padding: "2px 8px",
                        borderRadius: 5,
                        color: "#334155",
                        fontFamily: "'JetBrains Mono', Menlo, monospace",
                      }}
                    >
                      {tc.route}
                    </code>
                    {tc.framework && (
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          padding: "2px 8px",
                          borderRadius: 5,
                          background: "#dbeafe",
                          color: "#2563eb",
                        }}
                      >
                        {tc.framework}
                      </span>
                    )}
                  </div>
                  <p style={{ fontSize: 12.5, color: "#475569", lineHeight: 1.6, margin: "0 0 8px" }}>
                    {tc.description}
                  </p>
                  <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                    {tc.fields && tc.fields.length > 0 && (
                      <span style={{ fontSize: 11, color: "#64748b" }}>📋 {tc.fields.join(", ")}</span>
                    )}
                    {tc.actions && tc.actions.length > 0 && (
                      <span style={{ fontSize: 11, color: "#64748b" }}>▶️ {tc.actions.join(", ")}</span>
                    )}
                    {(!tc.fields || tc.fields.length === 0) && (!tc.actions || tc.actions.length === 0) && (
                      <span style={{ fontSize: 11, color: "#94a3b8" }}>👁️ {tc.interaction}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── API Test Cases ── */}
          <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, overflow: "hidden" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "12px 16px",
                background: "#f8fafc",
                borderBottom: "1px solid #e2e8f0",
              }}
            >
              <span style={{ fontWeight: 700, fontSize: 13.5, color: "#0f172a" }}>🔌 API Test Cases</span>
              <button
                onClick={onDownloadApi}
                disabled={loading}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "6px 12px",
                  borderRadius: 7,
                  border: "none",
                  background: "#16a34a",
                  color: "#fff",
                  fontSize: 11.5,
                  fontWeight: 700,
                  cursor: loading ? "not-allowed" : "pointer",
                  opacity: loading ? 0.6 : 1,
                }}
              >
                ⬇ Download
              </button>
            </div>
            <div style={{ maxHeight: 360, overflowY: "auto" }}>
              {apiTestCases.length === 0 && (
                <div style={{ padding: "18px 16px", fontSize: 12, color: "#94a3b8" }}>
                  No API endpoints detected for this project.
                </div>
              )}
              {apiTestCases.map((tc, idx) => (
                <div
                  key={`api-${idx}`}
                  style={{
                    padding: "14px 16px",
                    borderBottom: idx === apiTestCases.length - 1 ? "none" : "1px solid #f1f5f9",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8" }}>#{idx + 1}</span>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 800,
                        padding: "2px 8px",
                        borderRadius: 5,
                        background: methodColor(tc.method),
                        color: "#fff",
                      }}
                    >
                      {tc.method}
                    </span>
                    <code
                      style={{
                        fontSize: 12,
                        background: "#f1f5f9",
                        padding: "2px 8px",
                        borderRadius: 5,
                        color: "#334155",
                        fontFamily: "'JetBrains Mono', Menlo, monospace",
                      }}
                    >
                      {tc.path}
                    </code>
                    {tc.controller && (
                      <span style={{ fontSize: 11, color: "#94a3b8" }}>— {tc.controller}</span>
                    )}
                  </div>
                  <p style={{ fontSize: 12.5, color: "#475569", lineHeight: 1.6, margin: "0 0 8px" }}>
                    {tc.description}
                  </p>
                  <div style={{ fontSize: 11, color: "#64748b" }}>
                    Expected:{" "}
                    <span
                      style={{
                        fontWeight: 700,
                        padding: "2px 8px",
                        borderRadius: 5,
                        background: "#dcfce7",
                        color: "#16a34a",
                      }}
                    >
                      {tc.expectedStatus}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {preview && (
          <div
            style={{
              marginTop: 16,
              padding: "10px 14px",
              borderRadius: 8,
              background: "#f0fdf4",
              border: "1px solid #bbf7d0",
              fontSize: 12.5,
              color: "#166534",
              fontWeight: 600,
            }}
          >
            ✓ Generated: {uiTestCases.length || preview.uiTestCount} UI tests + {apiTestCases.length || preview.apiTestCount} API tests
          </div>
        )}
        {error && (
          <div
            style={{
              marginTop: 16,
              padding: "10px 14px",
              borderRadius: 8,
              background: "#fef2f2",
              border: "1px solid #fecaca",
              fontSize: 12.5,
              color: "#dc2626",
            }}
          >
            ⚠ {error}
          </div>
        )}
      </div>
    </div>
  );
}
