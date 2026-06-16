import React from "react";

interface DiffLineEntry {
  type: "add" | "remove" | "context" | "hunk";
  oldLineNumber: number | null;
  newLineNumber: number | null;
  content: string;
}

interface CodeChangeEntry {
  fileName: string;
  filePath: string;
  changeType: "modified" | "added" | "deleted";
  additions: number;
  deletions: number;
  oldContent: string;
  newContent: string;
  diffLines: DiffLineEntry[];
}

type StyleMap = Record<string, React.CSSProperties>;
type CodeChangeCategory = "source" | "tests" | "config" | "docs" | "other";

interface MigrationCodeChangesSectionProps {
  styles: StyleMap;
  reportCodeChanges: CodeChangeEntry[];
  visibleReportCodeChanges: CodeChangeEntry[];
  hasMoreReportCodeChanges: boolean;
  showCodeChanges: boolean;
  selectedDiffFile: string | null;
  setShowCodeChanges: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedDiffFile: React.Dispatch<React.SetStateAction<string | null>>;
  setVisibleReportDiffCount: React.Dispatch<React.SetStateAction<number>>;
  reportDiffsPageSize: number;
}

const categorizeCodeChange = (filePath: string): CodeChangeCategory => {
  const normalized = (filePath || "").replace(/\\/g, "/").toLowerCase();
  if (
    normalized.includes("/src/test/") ||
    normalized.includes("/tests/") ||
    normalized.endsWith(".spec.ts") ||
    normalized.endsWith(".test.ts") ||
    normalized.endsWith(".spec.tsx") ||
    normalized.endsWith(".test.tsx") ||
    normalized.endsWith("test.java")
  ) {
    return "tests";
  }
  if (
    normalized.includes("/src/main/") ||
    normalized.endsWith(".java") ||
    normalized.endsWith(".kt") ||
    normalized.endsWith(".groovy") ||
    normalized.endsWith(".ts") ||
    normalized.endsWith(".tsx") ||
    normalized.endsWith(".js") ||
    normalized.endsWith(".jsx") ||
    normalized.endsWith(".py")
  ) {
    return "source";
  }
  if (
    normalized.startsWith("docs/") ||
    normalized.endsWith(".md") ||
    normalized.endsWith(".adoc") ||
    normalized.endsWith(".txt")
  ) {
    return "docs";
  }
  if (
    normalized.endsWith("pom.xml") ||
    normalized.endsWith("build.gradle") ||
    normalized.endsWith("build.gradle.kts") ||
    normalized.endsWith("settings.gradle") ||
    normalized.endsWith("settings.gradle.kts") ||
    normalized.endsWith(".properties") ||
    normalized.endsWith(".yaml") ||
    normalized.endsWith(".yml") ||
    normalized.endsWith(".xml") ||
    normalized.endsWith(".json") ||
    normalized.endsWith(".toml") ||
    normalized.endsWith(".env") ||
    normalized.includes("dockerfile")
  ) {
    return "config";
  }
  return "other";
};

const categoryMeta: Record<CodeChangeCategory, { label: string; bg: string; text: string; border: string }> = {
  source: { label: "Source", bg: "#dbeafe", text: "#1d4ed8", border: "#bfdbfe" },
  tests: { label: "Tests", bg: "#dcfce7", text: "#166534", border: "#bbf7d0" },
  config: { label: "Config", bg: "#ede9fe", text: "#6d28d9", border: "#ddd6fe" },
  docs: { label: "Docs", bg: "#fef3c7", text: "#92400e", border: "#fde68a" },
  other: { label: "Other", bg: "#e2e8f0", text: "#475569", border: "#cbd5e1" },
};

const getChangeImpactLabel = (churn: number) =>
  churn >= 80 ? "High impact" : churn >= 20 ? "Medium impact" : "Targeted change";

export function MigrationCodeChangesSection({
  styles,
  reportCodeChanges,
  visibleReportCodeChanges,
  hasMoreReportCodeChanges,
  showCodeChanges,
  selectedDiffFile,
  setShowCodeChanges,
  setSelectedDiffFile,
  setVisibleReportDiffCount,
  reportDiffsPageSize,
}: MigrationCodeChangesSectionProps) {
  const summary = React.useMemo(() => {
    const additions = reportCodeChanges.reduce((sum, change) => sum + change.additions, 0);
    const deletions = reportCodeChanges.reduce((sum, change) => sum + change.deletions, 0);
    const categories: Record<CodeChangeCategory, number> = {
      source: 0,
      tests: 0,
      config: 0,
      docs: 0,
      other: 0,
    };

    reportCodeChanges.forEach((change) => {
      categories[categorizeCodeChange(change.filePath)] += 1;
    });

    return { additions, deletions, categories };
  }, [reportCodeChanges]);

  return (
    <div style={styles.reportSection}>
      <h3 style={{ ...styles.reportTitle, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Code Changes Review</span>
        <button
          onClick={() => setShowCodeChanges(!showCodeChanges)}
          style={{
            background: "none",
            border: "1px solid #d0d7de",
            borderRadius: 6,
            padding: "6px 12px",
            cursor: "pointer",
            fontSize: 12,
            color: "#24292f"
          }}
        >
          {showCodeChanges ? "Collapse" : "Expand"}
        </button>
      </h3>

      {showCodeChanges && (
        <div
          style={{
            border: "1px solid #d0d7de",
            borderRadius: 16,
            overflow: "hidden",
            backgroundColor: "#fff",
            boxShadow: "0 18px 38px rgba(15, 23, 42, 0.06)",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 16,
              padding: "18px 20px",
              background: "linear-gradient(135deg, #f8fbff 0%, #eef5ff 52%, #f8fafc 100%)",
              borderBottom: "1px solid #d0d7de",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
                  <span style={{ fontWeight: 700, fontSize: 20, color: "#0f172a" }}>Live migration diff</span>
                  <span
                    style={{
                      fontSize: 11,
                      padding: "5px 10px",
                      backgroundColor: "#dbeafe",
                      borderRadius: 999,
                      color: "#1d4ed8",
                      fontWeight: 700,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                    }}
                  >
                    Git-backed
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      padding: "5px 10px",
                      backgroundColor: "#ecfeff",
                      borderRadius: 999,
                      color: "#0f766e",
                      fontWeight: 700,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                    }}
                  >
                    Cache artifacts excluded
                  </span>
                </div>
                <span style={{ color: "#475569", fontSize: 13, lineHeight: 1.5, maxWidth: 820 }}>
                  This review is generated from the migrated working copy using real unified diffs. It highlights source, test, config, and docs changes instead of transient scan/cache output.
                </span>
              </div>
              <span
                style={{
                  fontSize: 11,
                  padding: "6px 12px",
                  backgroundColor: "#ffffff",
                  borderRadius: 999,
                  color: "#0f172a",
                  fontWeight: 700,
                  border: "1px solid #d0d7de",
                }}
              >
                Read only
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
              <div style={{ padding: "14px 16px", borderRadius: 14, backgroundColor: "#ffffff", border: "1px solid #dbe7ff" }}>
                <div style={{ color: "#64748b", fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Files
                </div>
                <div style={{ marginTop: 6, fontSize: 24, fontWeight: 800, color: "#0f172a" }}>{reportCodeChanges.length}</div>
                <div style={{ marginTop: 4, color: "#64748b", fontSize: 12 }}>Showing {visibleReportCodeChanges.length} now</div>
              </div>
              <div style={{ padding: "14px 16px", borderRadius: 14, backgroundColor: "#ffffff", border: "1px solid #dcfce7" }}>
                <div style={{ color: "#64748b", fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Line churn
                </div>
                <div style={{ marginTop: 6, display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ fontSize: 22, fontWeight: 800, color: "#16a34a" }}>+{summary.additions}</span>
                  <span style={{ fontSize: 22, fontWeight: 800, color: "#dc2626" }}>-{summary.deletions}</span>
                </div>
                <div style={{ marginTop: 4, color: "#64748b", fontSize: 12 }}>
                  Net {summary.additions - summary.deletions >= 0 ? "+" : ""}{summary.additions - summary.deletions} lines
                </div>
              </div>
              {(["source", "tests", "config", "docs"] as CodeChangeCategory[]).map((category) => (
                <div
                  key={category}
                  style={{
                    padding: "14px 16px",
                    borderRadius: 14,
                    backgroundColor: "#ffffff",
                    border: `1px solid ${categoryMeta[category].border}`,
                  }}
                >
                  <div style={{ color: "#64748b", fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {categoryMeta[category].label}
                  </div>
                  <div style={{ marginTop: 6, fontSize: 24, fontWeight: 800, color: categoryMeta[category].text }}>
                    {summary.categories[category]}
                  </div>
                  <div style={{ marginTop: 4, color: "#64748b", fontSize: 12 }}>
                    {summary.categories[category] === 1 ? "review item" : "review items"}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              padding: "10px 18px",
              backgroundColor: "#ffffff",
              borderBottom: "1px solid #d0d7de",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
              <span style={{ color: "#0f172a", fontSize: 13, fontWeight: 700 }}>Review queue</span>
              <span style={{ color: "#64748b", fontSize: 13 }}>
                {visibleReportCodeChanges.length} of {reportCodeChanges.length} files loaded
              </span>
            </div>
            <span style={{ color: "#64748b", fontSize: 12 }}>Select a file to inspect line-level changes</span>
          </div>

          <div style={{ maxHeight: 600, overflowY: "auto" }}>
            {visibleReportCodeChanges.map((change, idx) => {
              const category = categorizeCodeChange(change.filePath);
              const meta = categoryMeta[category];
              const totalChurn = change.additions + change.deletions;

              return (
                <div key={idx}>
                  <div
                    onClick={() => setSelectedDiffFile(selectedDiffFile === change.filePath ? null : change.filePath)}
                    className={selectedDiffFile === change.filePath ? undefined : "ui-hover-row"}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "14px 18px",
                      backgroundColor: selectedDiffFile === change.filePath ? "#eff6ff" : "#ffffff",
                      borderBottom: "1px solid #d0d7de",
                      cursor: "pointer",
                      transition: "background-color 0.15s",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, minWidth: 0 }}>
                      <span
                        style={{
                          marginTop: 2,
                          width: 24,
                          height: 24,
                          borderRadius: 999,
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          backgroundColor: selectedDiffFile === change.filePath ? "#dbeafe" : "#f8fafc",
                          color: "#1d4ed8",
                          fontSize: 12,
                          fontWeight: 800,
                          flexShrink: 0,
                        }}
                      >
                        {selectedDiffFile === change.filePath ? "v" : ">"}
                      </span>
                      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
                        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
                          <span
                            style={{
                              display: "inline-block",
                              padding: "3px 8px",
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                              backgroundColor: change.changeType === "added" ? "#dcfce7" : change.changeType === "deleted" ? "#fee2e2" : "#fef3c7",
                              color: change.changeType === "added" ? "#166534" : change.changeType === "deleted" ? "#991b1b" : "#92400e",
                              textTransform: "uppercase",
                              letterSpacing: "0.04em",
                            }}
                          >
                            {change.changeType}
                          </span>
                          <span
                            style={{
                              display: "inline-block",
                              padding: "3px 8px",
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                              backgroundColor: meta.bg,
                              color: meta.text,
                            }}
                          >
                            {meta.label}
                          </span>
                          <span
                            style={{
                              display: "inline-block",
                              padding: "3px 8px",
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                              backgroundColor: "#f8fafc",
                              color: "#475569",
                            }}
                          >
                            {getChangeImpactLabel(totalChurn)}
                          </span>
                        </div>
                        <span
                          style={{
                            fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                            fontSize: 13,
                            fontWeight: 700,
                            color: "#0f172a",
                            wordBreak: "break-word",
                          }}
                        >
                          {change.fileName}
                        </span>
                        <span
                          style={{
                            fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                            fontSize: 12,
                            color: "#64748b",
                            wordBreak: "break-word",
                          }}
                        >
                          {change.filePath}
                        </span>
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                      <div style={{ textAlign: "right" }}>
                        <div style={{ color: "#22c55e", fontSize: 13, fontWeight: 800 }}>+{change.additions}</div>
                        <div style={{ color: "#ef4444", fontSize: 13, fontWeight: 800 }}>-{change.deletions}</div>
                      </div>
                      <div
                        style={{
                          minWidth: 64,
                          padding: "8px 10px",
                          borderRadius: 12,
                          backgroundColor: "#f8fafc",
                          border: `1px solid ${meta.border}`,
                          textAlign: "center",
                        }}
                      >
                        <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                          Churn
                        </div>
                        <div style={{ marginTop: 2, fontSize: 15, fontWeight: 800, color: meta.text }}>{totalChurn}</div>
                      </div>
                    </div>
                  </div>

                  {selectedDiffFile === change.filePath && (
                    <div
                      style={{
                        backgroundColor: "#0d1117",
                        borderBottom: "1px solid #d0d7de",
                        overflowX: "auto",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "8px 16px",
                          backgroundColor: "#161b22",
                          borderBottom: "1px solid #30363d",
                        }}
                      >
                        <span
                          style={{
                            fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                            fontSize: 12,
                            color: "#8b949e",
                          }}
                        >
                          {change.fileName}
                        </span>
                        <div style={{ display: "flex", gap: 12 }}>
                          <span style={{ fontSize: 11, color: "#3fb950" }}>+{change.additions} lines</span>
                          <span style={{ fontSize: 11, color: "#f85149" }}>-{change.deletions} lines</span>
                        </div>
                      </div>

                      <div
                        style={{
                          fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                          fontSize: 12,
                          lineHeight: 1.5,
                        }}
                      >
                        {change.diffLines.map((line, lineIdx) =>
                          line.type === "hunk" ? (
                            <div
                              key={lineIdx}
                              style={{
                                display: "flex",
                                alignItems: "center",
                                backgroundColor: "#111827",
                                color: "#93c5fd",
                                borderTop: "1px solid #30363d",
                                borderBottom: "1px solid #30363d",
                              }}
                            >
                              <span style={{ minWidth: 50, padding: "2px 10px", borderRight: "1px solid #30363d" }} />
                              <span style={{ minWidth: 50, padding: "2px 10px", borderRight: "1px solid #30363d" }} />
                              <span style={{ minWidth: 20, padding: "2px 6px", textAlign: "center" }}>@</span>
                              <span style={{ flex: 1, padding: "2px 10px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                                {line.content}
                              </span>
                            </div>
                          ) : (
                            <div
                              key={lineIdx}
                              style={{
                                display: "flex",
                                backgroundColor:
                                  line.type === "add" ? "rgba(63, 185, 80, 0.15)" :
                                  line.type === "remove" ? "rgba(248, 81, 73, 0.15)" : "transparent",
                                borderLeft: `4px solid ${line.type === "add" ? "#3fb950" : line.type === "remove" ? "#f85149" : "transparent"}`,
                              }}
                            >
                              <span
                                style={{
                                  minWidth: 50,
                                  padding: "2px 10px",
                                  textAlign: "right",
                                  color: "#6e7681",
                                  backgroundColor:
                                    line.type === "add" ? "rgba(63, 185, 80, 0.1)" :
                                    line.type === "remove" ? "rgba(248, 81, 73, 0.1)" : "#161b22",
                                  borderRight: "1px solid #30363d",
                                  userSelect: "none",
                                }}
                              >
                                {line.oldLineNumber ?? ""}
                              </span>
                              <span
                                style={{
                                  minWidth: 50,
                                  padding: "2px 10px",
                                  textAlign: "right",
                                  color: "#6e7681",
                                  backgroundColor:
                                    line.type === "add" ? "rgba(63, 185, 80, 0.1)" :
                                    line.type === "remove" ? "rgba(248, 81, 73, 0.1)" : "#161b22",
                                  borderRight: "1px solid #30363d",
                                  userSelect: "none",
                                }}
                              >
                                {line.newLineNumber ?? ""}
                              </span>
                              <span
                                style={{
                                  minWidth: 20,
                                  padding: "2px 6px",
                                  textAlign: "center",
                                  color: line.type === "add" ? "#3fb950" : line.type === "remove" ? "#f85149" : "#8b949e",
                                  fontWeight: 600,
                                  userSelect: "none",
                                }}
                              >
                                {line.type === "add" ? "+" : line.type === "remove" ? "-" : " "}
                              </span>
                              <span
                                style={{
                                  flex: 1,
                                  padding: "2px 10px",
                                  color: line.type === "add" ? "#aff5b4" : line.type === "remove" ? "#ffa198" : "#c9d1d9",
                                  whiteSpace: "pre-wrap",
                                  wordBreak: "break-word",
                                }}
                              >
                                {line.content || " "}
                              </span>
                            </div>
                          )
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {reportCodeChanges.length === 0 && (
              <div style={{ padding: 40, textAlign: "center", color: "#57606a" }}>
                No code changes to display
              </div>
            )}

            {hasMoreReportCodeChanges && (
              <div
                style={{
                  padding: "16px",
                  display: "flex",
                  justifyContent: "center",
                  backgroundColor: "#fff",
                  borderTop: "1px solid #d0d7de",
                }}
              >
                <button
                  onClick={() =>
                    setVisibleReportDiffCount((current) =>
                      Math.min(current + reportDiffsPageSize, reportCodeChanges.length)
                    )
                  }
                  style={{
                    backgroundColor: "#fff",
                    border: "1px solid #d0d7de",
                    borderRadius: 8,
                    padding: "10px 16px",
                    cursor: "pointer",
                    fontSize: 13,
                    fontWeight: 600,
                    color: "#0969da",
                  }}
                >
                  Load more files ({reportCodeChanges.length - visibleReportCodeChanges.length} remaining)
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
