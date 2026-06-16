import React, { useState } from "react";

interface MicroserviceAssessmentProps {
  repoAnalysis: any;
  microserviceResult: any;
  microserviceLoading: boolean;
  loading: boolean;
  handleCheckMicroserviceEligibility: () => void;
  conversionDecision: "yes" | "no" | null;
  setConversionDecision: (val: "yes" | "no" | null) => void;
  showFolderStructure: boolean;
  setShowFolderStructure: (val: boolean) => void;
  styles: any;
}

export default function MicroserviceAssessment({
  repoAnalysis,
  microserviceResult,
  microserviceLoading,
  loading,
  handleCheckMicroserviceEligibility,
  conversionDecision,
  setConversionDecision,
  showFolderStructure,
  setShowFolderStructure,
  styles,
}: MicroserviceAssessmentProps) {
  const [microserviceView, setMicroserviceView] = useState<"criteria" | "flowchart">("flowchart");
  const [selectedChunk, setSelectedChunk] = useState<any | null>(null);

  if (!repoAnalysis) return null;

  return (
    <div style={{ ...styles.structureBox, marginTop: 20 }}>
      <div style={{ ...styles.structureTitle, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>🏗️ Microservice Eligibility Assessment</span>
        {microserviceResult && (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              style={{
                padding: "7px 16px",
                borderRadius: 8,
                border: "2px solid #6366f1",
                background: "linear-gradient(135deg, #6366f1, #4f46e5)",
                color: "#fff",
                fontWeight: 600,
                fontSize: 12,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                transition: "all 0.2s ease"
              }}
              onClick={() => setMicroserviceView("flowchart")}
            >
              🔄 Assessment Flowchart
            </button>
          </div>
        )}
      </div>
      <div style={{ padding: "12px 0" }}>

        {/* Loading state */}
        {!microserviceResult && loading && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 20px", background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0" }}>
            <span style={{ fontSize: 20 }}>[Loading]</span>
            <span style={{ fontSize: 14, color: "#64748b" }}>Analyzing microservice eligibility...</span>
          </div>
        )}

        {/* No result */}
        {!microserviceResult && !loading && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 20px", background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0" }}>
            <span style={{ fontSize: 20 }}>[i]</span>
            <div>
              <span style={{ fontSize: 14, color: "#64748b" }}>Microservice assessment not available for this repository.</span>
              <button
                style={{ ...styles.secondaryBtn, fontSize: 12, padding: "4px 12px", marginLeft: 12 }}
                onClick={handleCheckMicroserviceEligibility}
                disabled={microserviceLoading}
              >
                {microserviceLoading ? "[Loading] Analyzing..." : "[Refresh] Retry"}
              </button>
            </div>
          </div>
        )}

        {/* Results */}
        {microserviceResult && (
          <div>

            {/* FLOWCHART VIEW */}
            {microserviceView === "flowchart" && (
              <div style={{ marginBottom: 20, borderRadius: 12, overflow: "hidden", border: "1px solid #e2e8f0", background: "#fff" }}>
                <div style={{ background: "linear-gradient(135deg, #312e81, #4338ca)", padding: "16px 20px", textAlign: "center" }}>
                  <span style={{ fontSize: 16, fontWeight: 700, color: "#fff" }}>Microservice Eligibility Assessment Flow</span>
                  <div style={{ fontSize: 11, color: "#c7d2fe", marginTop: 4 }}>(Chunk + Overall Application Score)</div>
                </div>

                <div style={{ padding: "24px 20px" }}>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
                    <div style={{ padding: "12px 24px", background: "#dbeafe", border: "2px solid #3b82f6", borderRadius: 10, fontWeight: 600, fontSize: 13, color: "#1e40af", textAlign: "center" }}>
                      1. Input Application Repository<br/>
                      <span style={{ fontSize: 11, fontWeight: 400, color: "#3b82f6" }}>Java / Spring Boot • Source Code • pom.xml / build.gradle</span>
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    <div style={{ padding: "12px 24px", background: "#e0e7ff", border: "2px solid #6366f1", borderRadius: 10, fontWeight: 600, fontSize: 13, color: "#3730a3", textAlign: "center" }}>
                      2. Static Code Analysis<br/>
                      <span style={{ fontSize: 11, fontWeight: 400, color: "#6366f1" }}>Scan: Controllers • Services • Repositories • Entities • Dependencies</span>
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    <div style={{ padding: "12px 24px", background: "#fef3c7", border: "2px solid #f59e0b", borderRadius: 10, fontWeight: 600, fontSize: 13, color: "#92400e", textAlign: "center" }}>
                      3. Identify All Controllers<br/>
                      <span style={{ fontSize: 11, fontWeight: 400, color: "#b45309" }}>
                        {microserviceResult.controllers_count || 0} controller(s) found: {microserviceResult.chunk_results?.filter((c: any) => c.controller).map((c: any) => c.controller).join(", ") || "None"}
                      </span>
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    <div style={{ padding: "10px 24px", background: "#f1f5f9", border: "2px solid #64748b", borderRadius: 10, fontWeight: 600, fontSize: 13, color: "#334155", textAlign: "center" }}>
                      4. Iterate Through Each Controller → Form Chunks
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    {/* Chunk Formation Visual */}
                    <div style={{ width: "100%", padding: "16px", background: "#f8fafc", borderRadius: 12, border: "1px dashed #94a3b8", marginBottom: 4 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#475569", marginBottom: 12, textAlign: "center" }}>Steps 5-8: Chunk Formation (per controller)</div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
                        {microserviceResult.chunk_results?.map((chunk: any, idx: number) => (
                          <div key={idx} style={{
                            padding: "10px 14px",
                            borderRadius: 8,
                            border: `1px solid ${chunk.score >= 70 ? "#86efac" : chunk.score >= 51 ? "#fcd34d" : "#fca5a5"}`,
                            background: chunk.score >= 70 ? "#f0fdf4" : chunk.score >= 51 ? "#fffbeb" : "#fef2f2"
                          }}>
                            <div style={{ fontSize: 12, fontWeight: 700, color: "#1e293b" }}>{chunk.chunk_name}</div>
                            <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
                              {chunk.controller ? `Controller → ${(chunk.services || []).length} Service(s)` : "No Controller"}
                              {(chunk.entities || []).length > 0 ? ` → ${chunk.entities.length} Entity` : ""}
                              {(chunk.repositories || []).length > 0 ? ` → ${chunk.repositories.length} Repo` : ""}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    <div style={{ padding: "12px 24px", background: "#ede9fe", border: "2px solid #8b5cf6", borderRadius: 10, fontWeight: 600, fontSize: 13, color: "#5b21b6", textAlign: "center" }}>
                      9-11. Run Chunk-Level Eligibility Analysis<br/>
                      <span style={{ fontSize: 11, fontWeight: 400, color: "#7c3aed" }}>
                        Scoring: {microserviceResult.criteria_option === "OPTION_1_WITH_DATABASE" ? "Option 1 (With DB: 4×25%)" : "Option 2 (No DB: 50%+30%+20%)"}
                      </span>
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
                      <span style={{ padding: "6px 14px", borderRadius: 6, fontSize: 11, fontWeight: 600, background: "#fee2e2", color: "#991b1b", border: "1px solid #fca5a5" }}>0-50% Not Suitable</span>
                      <span style={{ padding: "6px 14px", borderRadius: 6, fontSize: 11, fontWeight: 600, background: "#fef3c7", color: "#92400e", border: "1px solid #fcd34d" }}>51-69% Refactor Required</span>
                      <span style={{ padding: "6px 14px", borderRadius: 6, fontSize: 11, fontWeight: 600, background: "#dcfce7", color: "#166534", border: "1px solid #86efac" }}>70-80% Good Candidate</span>
                      <span style={{ padding: "6px 14px", borderRadius: 6, fontSize: 11, fontWeight: 600, background: "#bbf7d0", color: "#166534", border: "1px solid #4ade80" }}>81-100% Highly Suitable</span>
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    <div style={{ padding: "10px 24px", background: "#f1f5f9", border: "2px solid #64748b", borderRadius: 10, fontWeight: 600, fontSize: 13, color: "#334155", textAlign: "center" }}>
                      13. Store Chunk Results → Repeat for Next Controller
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    {/* Step 14: Overall Analysis */}
                    <div style={{ padding: "14px 24px", background: "#dbeafe", border: "2px solid #2563eb", borderRadius: 10, fontWeight: 600, fontSize: 13, color: "#1e40af", textAlign: "center", width: "100%" }}>
                      <div>14. Overall Application Analysis</div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginTop: 10 }}>
                        <div style={{ padding: "8px", background: "#eff6ff", borderRadius: 6, fontSize: 11 }}>
                          <div style={{ fontWeight: 700 }}>14.1 Collect Results</div>
                          <div style={{ color: "#3b82f6" }}>{microserviceResult.chunk_summary?.total_chunks || 0} chunks</div>
                        </div>
                        <div style={{ padding: "8px", background: "#eff6ff", borderRadius: 6, fontSize: 11 }}>
                          <div style={{ fontWeight: 700 }}>14.2 Weighted Score</div>
                          <div style={{ color: "#3b82f6", fontWeight: 700, fontSize: 14 }}>{microserviceResult.chunk_summary?.overall_weighted_score || microserviceResult.score}%</div>
                        </div>
                        <div style={{ padding: "8px", background: "#eff6ff", borderRadius: 6, fontSize: 11 }}>
                          <div style={{ fontWeight: 700 }}>14.3 Eligible Ratio</div>
                          <div style={{ color: "#3b82f6" }}>{microserviceResult.chunk_summary?.eligible_chunks || 0}/{microserviceResult.chunk_summary?.total_chunks || 0} = {microserviceResult.chunk_summary?.eligible_chunk_ratio || 0}%</div>
                        </div>
                      </div>
                    </div>
                    <div style={{ width: 2, height: 20, background: "#94a3b8" }} />

                    {/* Step 15: Final Output */}
                    <div style={{ padding: "14px 24px", border: "3px solid", borderColor: microserviceResult.score >= 70 ? "#22c55e" : microserviceResult.score >= 51 ? "#f59e0b" : "#ef4444", borderRadius: 12, background: microserviceResult.score >= 70 ? "#f0fdf4" : microserviceResult.score >= 51 ? "#fffbeb" : "#fef2f2", textAlign: "center", width: "100%" }}>
                      <div style={{ fontSize: 14, fontWeight: 800, color: "#1e293b", marginBottom: 8 }}>15. Final Scorecard Output</div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                        <div style={{ padding: "8px", background: "#fff", borderRadius: 6, border: "1px solid #e2e8f0" }}>
                          <div style={{ fontSize: 10, color: "#64748b" }}>15.1 Chunk Results</div>
                          {microserviceResult.chunk_results?.map((cr: any, i: number) => (
                            <div key={i} style={{ fontSize: 11, marginTop: 2 }}>
                              <span style={{ fontWeight: 600 }}>{cr.chunk_name}</span> → <span style={{ color: cr.score >= 70 ? "#166534" : cr.score >= 51 ? "#92400e" : "#991b1b", fontWeight: 700 }}>{cr.score}%</span>
                              <span style={{ marginLeft: 4, fontSize: 10, color: cr.score >= 70 ? "#22c55e" : cr.score >= 51 ? "#f59e0b" : "#ef4444" }}>{cr.label}</span>
                            </div>
                          ))}
                        </div>
                        <div style={{ padding: "8px", background: "#fff", borderRadius: 6, border: "1px solid #e2e8f0" }}>
                          <div style={{ fontSize: 10, color: "#64748b" }}>15.2 Overall Results</div>
                          <div style={{ fontSize: 12, marginTop: 4 }}>Score: <strong>{microserviceResult.score}%</strong></div>
                          <div style={{ fontSize: 12 }}>Eligible Ratio: <strong>{microserviceResult.chunk_summary?.eligible_chunk_ratio || 0}%</strong></div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: microserviceResult.score >= 70 ? "#166534" : microserviceResult.score >= 51 ? "#92400e" : "#991b1b" }}>
                            {microserviceResult.eligibility_label}
                          </div>
                        </div>
                        <div style={{ padding: "8px", background: "#fff", borderRadius: 6, border: "1px solid #e2e8f0" }}>
                          <div style={{ fontSize: 10, color: "#64748b" }}>15.3 Recommendation</div>
                          <div style={{ fontSize: 11, marginTop: 4, color: "#475569", lineHeight: 1.4 }}>
                            {microserviceResult.score >= 70
                              ? "Proceed with phased microservice migration starting from highly eligible business domains."
                              : microserviceResult.score >= 51
                              ? "Partial migration possible. Refactor weak modules before full adoption."
                              : "Not recommended. Stay monolith or refactor first."}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Additional Rule Note */}
                  <div style={{ marginTop: 16, padding: "10px 16px", background: "#eff6ff", borderRadius: 8, border: "1px solid #bfdbfe", fontSize: 11, color: "#1e40af" }}>
                    <strong>Additional Rule:</strong> If at least one critical business CHUNK is eligible, phased microservice migration can begin. 
                    Current: <strong>{microserviceResult.chunk_summary?.eligible_chunks || 0}</strong> eligible chunk(s) out of <strong>{microserviceResult.chunk_summary?.total_chunks || 0}</strong>.
                  </div>
                </div>
              </div>
            )}

            {/* SECTION 2: Three Panel Row */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 20 }}>
              <div style={{
                padding: "20px", borderRadius: 12,
                background: microserviceResult.score >= 70 ? "linear-gradient(135deg, #dcfce7, #bbf7d0)" : microserviceResult.score >= 51 ? "linear-gradient(135deg, #fef3c7, #fde68a)" : "linear-gradient(135deg, #fee2e2, #fecaca)",
                border: microserviceResult.score >= 70 ? "1px solid #86efac" : microserviceResult.score >= 51 ? "1px solid #fcd34d" : "1px solid #fca5a5",
                textAlign: "center"
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#64748b", marginBottom: 8 }}>2. Microservices Eligibility</div>
                <div style={{
                  display: "inline-block", padding: "8px 20px", borderRadius: 25, fontSize: 14, fontWeight: 700,
                  background: microserviceResult.score >= 70 ? "#166534" : microserviceResult.score >= 51 ? "#92400e" : "#991b1b", color: "#fff"
                }}>
                  {(microserviceResult.eligibility_label === "Not Suitable" ? "Not Recommended" : microserviceResult.eligibility_label) || (microserviceResult.score >= 70 ? "ELIGIBLE" : microserviceResult.score >= 51 ? "INTERMEDIATE" : "NOT RECOMMENDED")}
                </div>
              </div>

              <div style={{ padding: "20px", borderRadius: 12, background: "#f8fafc", border: "1px solid #e2e8f0", textAlign: "center" }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#64748b", marginBottom: 12 }}>Overall Score</div>
                <div style={{ position: "relative", width: 100, height: 100, margin: "0 auto" }}>
                  <svg width="100" height="100" viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="40" fill="none" stroke="#e5e7eb" strokeWidth="12" />
                    <circle cx="50" cy="50" r="40" fill="none"
                      stroke={microserviceResult.score >= 70 ? "#22c55e" : microserviceResult.score >= 51 ? "#f59e0b" : "#ef4444"}
                      strokeWidth="12" strokeDasharray={`${(microserviceResult.score / 100) * 251.2} 251.2`}
                      strokeLinecap="round" transform="rotate(-90 50 50)" />
                  </svg>
                  <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", fontSize: 22, fontWeight: 800, color: microserviceResult.score >= 70 ? "#166534" : microserviceResult.score >= 51 ? "#92400e" : "#991b1b" }}>
                    {microserviceResult.score}%
                  </div>
                </div>
              </div>

              <div style={{ padding: "20px", borderRadius: 12, background: "#eff6ff", border: "1px solid #bfdbfe" }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#1e40af", marginBottom: 10 }}>3. How to Justify</div>
                <div style={{ fontSize: 12, color: "#1e3a8a", lineHeight: 1.6 }}>{microserviceResult.reasoning}</div>
              </div>
            </div>

            {/* Score Range Reference */}
            <div style={{ marginBottom: 20, padding: "16px", background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#64748b", marginBottom: 10 }}>Score Range Reference:</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                <span style={{ padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: "#fee2e2", color: "#991b1b", border: "1px solid #fca5a5" }}>0-50% Not Suitable</span>
                <span style={{ padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: "#fef3c7", color: "#92400e", border: "1px solid #fcd34d" }}>51-69% Refactor Required</span>
                <span style={{ padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: "#dcfce7", color: "#166534", border: "1px solid #86efac" }}>70-80% Good Candidate</span>
                <span style={{ padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: "#bbf7d0", color: "#166534", border: "1px solid #4ade80" }}>81-100% Highly Suitable</span>
              </div>
            </div>

            {/* SECTION 3: Chunk-Level Module Analysis */}
            {microserviceResult.chunk_results && microserviceResult.chunk_results.length > 0 && (
              <div style={{ marginBottom: 20, borderRadius: 12, overflow: "hidden", border: "1px solid #e2e8f0" }}>
                <div style={{ background: "linear-gradient(135deg, #312e81, #4338ca)", padding: "16px 20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 18 }}>🧩</span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: "#fff" }}>Module-Level Chunk Analysis</span>
                  </div>
                  {microserviceResult.chunk_summary && (
                    <div style={{ display: "flex", gap: 8 }}>
                      <span style={{ padding: "4px 10px", background: "#22c55e", color: "#fff", borderRadius: 6, fontSize: 11, fontWeight: 600 }}>✓ {microserviceResult.chunk_summary.eligible_chunks} Eligible</span>
                      <span style={{ padding: "4px 10px", background: "#f59e0b", color: "#fff", borderRadius: 6, fontSize: 11, fontWeight: 600 }}>⟳ {microserviceResult.chunk_summary.refactor_chunks} Refactor</span>
                      <span style={{ padding: "4px 10px", background: "#ef4444", color: "#fff", borderRadius: 6, fontSize: 11, fontWeight: 600 }}>✗ {microserviceResult.chunk_summary.not_suitable_chunks} Not Suitable</span>
                    </div>
                  )}
                </div>

                <div style={{ padding: "16px 20px", background: "#fff" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
                    {microserviceResult.chunk_results.map((chunk: any, idx: number) => (
                      <div key={idx} style={{
                        padding: "14px 16px", borderRadius: 10,
                        border: `2px solid ${chunk.score >= 70 ? "#86efac" : chunk.score >= 51 ? "#fcd34d" : "#fca5a5"}`,
                        background: chunk.score >= 70 ? "#f0fdf4" : chunk.score >= 51 ? "#fffbeb" : "#fef2f2",
                        cursor: "pointer", transition: "transform 0.15s, box-shadow 0.15s"
                      }}
                        onClick={() => setSelectedChunk(chunk)}
                        onMouseOver={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.1)"; }}
                        onMouseOut={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>{chunk.chunk_name}</div>
                          <span style={{ padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700, background: chunk.score >= 70 ? "#166534" : chunk.score >= 51 ? "#92400e" : "#991b1b", color: "#fff" }}>{chunk.score}%</span>
                        </div>
                        <div style={{ marginBottom: 8 }}>
                          <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: chunk.score >= 81 ? "#bbf7d0" : chunk.score >= 70 ? "#dcfce7" : chunk.score >= 51 ? "#fef3c7" : "#fee2e2", color: chunk.score >= 70 ? "#166534" : chunk.score >= 51 ? "#92400e" : "#991b1b" }}>{chunk.label}</span>
                          {chunk.criteria_option && chunk.criteria_option !== "N/A" && (
                            <span style={{ marginLeft: 6, padding: "2px 6px", borderRadius: 4, fontSize: 9, fontWeight: 500, background: "#e0e7ff", color: "#3730a3" }}>{chunk.criteria_option === "OPTION_1" ? "With DB" : "No DB"}</span>
                          )}
                        </div>
                        <div style={{ width: "100%", height: 6, background: "#e5e7eb", borderRadius: 3, marginBottom: 8, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${chunk.score}%`, background: chunk.score >= 70 ? "#22c55e" : chunk.score >= 51 ? "#f59e0b" : "#ef4444", borderRadius: 3, transition: "width 0.5s ease" }} />
                        </div>
                        {chunk.controller && <div style={{ fontSize: 11, color: "#475569", marginBottom: 4 }}><strong>Controller:</strong> {chunk.controller}</div>}
                        {chunk.services && chunk.services.length > 0 && <div style={{ fontSize: 11, color: "#475569", marginBottom: 4 }}><strong>Services:</strong> {chunk.services.join(", ")}</div>}
                        {((chunk.entities && chunk.entities.length > 0) || (chunk.repositories && chunk.repositories.length > 0)) && (
                          <div style={{ fontSize: 11, color: "#475569", marginBottom: 4 }}>
                            {chunk.entities && chunk.entities.length > 0 && <span><strong>Entities:</strong> {chunk.entities.join(", ")} </span>}
                            {chunk.repositories && chunk.repositories.length > 0 && <span><strong>Repos:</strong> {chunk.repositories.join(", ")}</span>}
                          </div>
                        )}
                        <div style={{ fontSize: 10, color: "#64748b", fontStyle: "italic", marginTop: 4 }}>{chunk.reason}</div>
                        <div style={{ fontSize: 10, color: "#475569", marginTop: 6, textAlign: "center", fontWeight: 700 }}>📊 Click to view criteria details</div>
                      </div>
                    ))}
                  </div>

                  {microserviceResult.chunk_summary && (
                    <div style={{ marginTop: 14, padding: "12px 16px", background: "#f1f5f9", borderRadius: 8, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                      <div style={{ fontSize: 12, color: "#475569" }}><strong>Overall Method:</strong> {microserviceResult.chunk_summary.scoring_method}</div>
                      <div style={{ display: "flex", gap: 12 }}>
                        <span style={{ fontSize: 12, color: "#475569" }}><strong>Weighted Score:</strong> <span style={{ color: microserviceResult.chunk_summary.overall_weighted_score >= 70 ? "#166534" : microserviceResult.chunk_summary.overall_weighted_score >= 51 ? "#92400e" : "#991b1b", fontWeight: 700 }}>{microserviceResult.chunk_summary.overall_weighted_score}%</span></span>
                        <span style={{ fontSize: 12, color: "#475569" }}><strong>Eligible Ratio:</strong> <span style={{ fontWeight: 700 }}>{microserviceResult.chunk_summary.eligible_chunk_ratio}%</span></span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* CHUNK CRITERIA POPUP MODAL */}
            {selectedChunk && (
              <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.5)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={() => setSelectedChunk(null)}>
                <div style={{ background: "#fff", borderRadius: 16, width: "100%", maxWidth: 750, boxShadow: "0 25px 50px rgba(0,0,0,0.25)" }} onClick={e => e.stopPropagation()}>
                  <div style={{ background: "linear-gradient(135deg, #1e293b, #334155)", padding: "20px 24px", borderRadius: "16px 16px 0 0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: "#fff" }}>{selectedChunk.chunk_name}</div>
                      <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
                        {selectedChunk.controller && `Controller: ${selectedChunk.controller}`}
                        {selectedChunk.services?.length > 0 && ` • ${selectedChunk.services.length} service(s)`}
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span style={{ padding: "6px 14px", borderRadius: 20, fontSize: 16, fontWeight: 800, background: selectedChunk.score >= 70 ? "#22c55e" : selectedChunk.score >= 51 ? "#f59e0b" : "#ef4444", color: "#fff" }}>{selectedChunk.score}%</span>
                      <button onClick={() => setSelectedChunk(null)} style={{ background: "rgba(255,255,255,0.1)", border: "none", color: "#fff", width: 32, height: 32, borderRadius: 8, cursor: "pointer", fontSize: 18 }}>✕</button>
                    </div>
                  </div>
                  <div style={{ padding: "16px 24px", borderBottom: "1px solid #e2e8f0", display: "flex", gap: 10, alignItems: "center" }}>
                    <span style={{ padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: selectedChunk.score >= 70 ? "#dcfce7" : selectedChunk.score >= 51 ? "#fef3c7" : "#fee2e2", color: selectedChunk.score >= 70 ? "#166534" : selectedChunk.score >= 51 ? "#92400e" : "#991b1b" }}>{selectedChunk.label}</span>
                    {selectedChunk.criteria_option && selectedChunk.criteria_option !== "N/A" && (
                      <span style={{ padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 500, background: "#e0e7ff", color: "#3730a3" }}>{selectedChunk.criteria_option === "OPTION_1" ? "Option 1: With Database" : "Option 2: Without Database"}</span>
                    )}
                  </div>
                  {selectedChunk.criteria && selectedChunk.criteria.length > 0 ? (
                    <div style={{ padding: "20px 24px" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                        <thead>
                          <tr style={{ background: "#f8fafc", borderBottom: "2px solid #e2e8f0" }}>
                            <th style={{ padding: "12px 16px", textAlign: "left", fontWeight: 600, color: "#475569" }}>Criteria</th>
                            <th style={{ padding: "12px 16px", textAlign: "center", fontWeight: 600, color: "#475569", width: 100 }}>Weightage</th>
                            <th style={{ padding: "12px 16px", textAlign: "center", fontWeight: 600, color: "#475569", width: 80 }}>Score (%)</th>
                            <th style={{ padding: "12px 16px", textAlign: "left", fontWeight: 600, color: "#475569" }}>Justification</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedChunk.criteria.map((c: any, i: number) => (
                            <tr key={i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                              <td style={{ padding: "14px 16px", fontWeight: 600, color: "#1e293b" }}>{c.name}</td>
                              <td style={{ padding: "14px 16px", textAlign: "center", color: "#64748b", fontWeight: 600 }}>{c.max_score}%</td>
                              <td style={{ padding: "14px 16px", textAlign: "center" }}>
                                <span style={{ fontWeight: 700, color: c.score_percent >= 70 ? "#22c55e" : c.score_percent >= 50 ? "#f59e0b" : "#ef4444" }}>{c.score_percent}%</span>
                              </td>
                              <td style={{ padding: "14px 16px", color: "#475569", fontSize: 12, lineHeight: 1.5 }}>{c.justification || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                        <tfoot>
                          <tr style={{ background: "#f8fafc", borderTop: "2px solid #e2e8f0" }}>
                            <td style={{ padding: "14px 16px", fontWeight: 700, color: "#1e293b" }}>Total</td>
                            <td style={{ padding: "14px 16px", textAlign: "center", fontWeight: 700, color: "#3b82f6" }}>100%</td>
                            <td style={{ padding: "14px 16px", textAlign: "center" }}>
                              <span style={{ fontWeight: 800, fontSize: 16, color: selectedChunk.score >= 70 ? "#22c55e" : selectedChunk.score >= 50 ? "#f59e0b" : "#ef4444" }}>{selectedChunk.score}%</span>
                            </td>
                            <td style={{ padding: "14px 16px" }}></td>
                          </tr>
                        </tfoot>
                      </table>
                    </div>
                  ) : (
                    <div style={{ padding: "30px 24px", textAlign: "center", color: "#64748b" }}>
                      <div style={{ fontSize: 14 }}>No detailed criteria available for this module.</div>
                      <div style={{ fontSize: 12, marginTop: 6 }}>{selectedChunk.reason}</div>
                    </div>
                  )}
                  <div style={{ padding: "16px 24px", borderTop: "1px solid #e2e8f0", background: "#f8fafc", borderRadius: "0 0 16px 16px" }}>
                    <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6, fontWeight: 600 }}>Components in this module:</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {selectedChunk.controller && <span style={{ padding: "3px 8px", background: "#dbeafe", color: "#1e40af", borderRadius: 4, fontSize: 10, fontWeight: 500 }}>🎯 {selectedChunk.controller}</span>}
                      {selectedChunk.services?.map((s: string, i: number) => <span key={i} style={{ padding: "3px 8px", background: "#e0e7ff", color: "#3730a3", borderRadius: 4, fontSize: 10, fontWeight: 500 }}>⚙️ {s}</span>)}
                      {selectedChunk.entities?.map((e: string, i: number) => <span key={i} style={{ padding: "3px 8px", background: "#fef3c7", color: "#92400e", borderRadius: 4, fontSize: 10, fontWeight: 500 }}>📦 {e}</span>)}
                      {selectedChunk.repositories?.map((r: string, i: number) => <span key={i} style={{ padding: "3px 8px", background: "#dcfce7", color: "#166534", borderRadius: 4, fontSize: 10, fontWeight: 500 }}>🗄️ {r}</span>)}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* SECTION 4A & 4B: Benefits & Risks */}
            {microserviceResult.score >= 70 && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
              <div style={{ padding: "16px", borderRadius: 12, background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#166534", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ background: "#22c55e", color: "#fff", borderRadius: "50%", width: 22, height: 22, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>4A</span>
                  Benefits if Converted
                </div>
                {microserviceResult.benefits_if_converted && microserviceResult.benefits_if_converted.length > 0 ? (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    {microserviceResult.benefits_if_converted.map((benefit: any, idx: number) => (
                      <div key={idx} style={{ padding: "10px 12px", background: "#fff", borderRadius: 8, border: "1px solid #dcfce7" }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "#166534", marginBottom: 4 }}>{benefit.icon || "✅"} {benefit.title}</div>
                        <div style={{ fontSize: 11, color: "#15803d", lineHeight: 1.4 }}>{benefit.description}</div>
                      </div>
                    ))}
                  </div>
                ) : <div style={{ fontSize: 12, color: "#86efac", fontStyle: "italic" }}>Benefits analysis not available</div>}
              </div>
              <div style={{ padding: "16px", borderRadius: 12, background: "#fef2f2", border: "1px solid #fecaca" }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#991b1b", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ background: "#ef4444", color: "#fff", borderRadius: "50%", width: 22, height: 22, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>4B</span>
                  Risks if NOT Converted
                </div>
                {microserviceResult.risks_if_not_converted && microserviceResult.risks_if_not_converted.length > 0 ? (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    {microserviceResult.risks_if_not_converted.map((risk: any, idx: number) => (
                      <div key={idx} style={{ padding: "10px 12px", background: "#fff", borderRadius: 8, border: "1px solid #fee2e2" }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "#991b1b", marginBottom: 4 }}>{risk.icon || "⚠️"} {risk.title}</div>
                        <div style={{ fontSize: 11, color: "#b91c1c", lineHeight: 1.4 }}>{risk.description}</div>
                      </div>
                    ))}
                  </div>
                ) : <div style={{ fontSize: 12, color: "#fca5a5", fontStyle: "italic" }}>Risk analysis not applicable</div>}
              </div>
            </div>
            )}

            {/* SECTION 5: Changes Needed (51-69%) */}
            {microserviceResult.score >= 51 && microserviceResult.score < 70 && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ padding: "16px", borderRadius: 12, background: "#fffbeb", border: "1px solid #fde68a" }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#92400e", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ background: "#f59e0b", color: "#fff", borderRadius: "50%", width: 22, height: 22, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>5</span>
                    Changes Needed for Microservices Adoption
                  </div>
                  {microserviceResult.changes_needed && microserviceResult.changes_needed.length > 0 ? (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                      {microserviceResult.changes_needed.map((change: any, idx: number) => (
                        <div key={idx} style={{ padding: "10px 12px", background: "#fff", borderRadius: 8, border: "1px solid #fef3c7" }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#92400e", marginBottom: 2 }}>📋 {change.title}</div>
                          <div style={{ fontSize: 11, color: "#b45309", lineHeight: 1.4 }}>{change.description}</div>
                        </div>
                      ))}
                    </div>
                  ) : <div style={{ fontSize: 12, color: "#fcd34d", fontStyle: "italic" }}>No specific changes identified</div>}
                </div>
              </div>
            )}

            {/* SECTION 5B: Why NOT Recommended (<=50%) */}
            {microserviceResult.score <= 50 && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ padding: "16px", borderRadius: 12, background: "#fef2f2", border: "1px solid #fecaca" }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#991b1b", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ background: "#ef4444", color: "#fff", borderRadius: "50%", width: 22, height: 22, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>!</span>
                    Why NOT Recommended
                  </div>
                  {microserviceResult.not_recommended_reasons && microserviceResult.not_recommended_reasons.length > 0 ? (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                      {microserviceResult.not_recommended_reasons.map((reason: any, idx: number) => (
                        <div key={idx} style={{ padding: "10px 12px", background: "#fff", borderRadius: 8, border: "1px solid #fee2e2" }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#991b1b", marginBottom: 2 }}>❌ {reason.title}</div>
                          <div style={{ fontSize: 11, color: "#b91c1c", lineHeight: 1.4 }}>{reason.description}</div>
                        </div>
                      ))}
                    </div>
                  ) : <div style={{ fontSize: 12, color: "#fca5a5", fontStyle: "italic" }}>No specific concerns identified</div>}
                </div>
              </div>
            )}

            {/* SECTION 6: Conversion Decision */}
            <div style={{ padding: "20px", borderRadius: 12, background: "#f8fafc", border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#1e293b", marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ background: "#6366f1", color: "#fff", borderRadius: "50%", width: 22, height: 22, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>6</span>
                Conversion Decision
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
                <label style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderRadius: 10,
                  background: conversionDecision === "yes" ? "#f0fdf4" : (microserviceResult.score < 70 ? "#f1f5f9" : "#f8fafc"),
                  border: conversionDecision === "yes" ? "2px solid #22c55e" : "1px solid #e2e8f0",
                  cursor: microserviceResult.score >= 70 ? "pointer" : "not-allowed",
                  opacity: microserviceResult.score < 70 ? 0.6 : 1, transition: "all 0.2s ease"
                }} onClick={() => { if (microserviceResult.score >= 70) setConversionDecision("yes"); }}>
                  <input type="radio" name="conversionDecision" checked={conversionDecision === "yes"} disabled={microserviceResult.score < 70}
                    onChange={() => { if (microserviceResult.score >= 70) setConversionDecision("yes"); }}
                    style={{ width: 18, height: 18, accentColor: "#22c55e", cursor: microserviceResult.score >= 70 ? "pointer" : "not-allowed" }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: conversionDecision === "yes" ? "#166534" : (microserviceResult.score < 70 ? "#9ca3af" : "#475569") }}>Yes, Convert to Microservices</div>
                    <div style={{ fontSize: 11, color: conversionDecision === "yes" ? "#15803d" : "#94a3b8", marginTop: 2 }}>Proceed with microservices migration</div>
                  </div>
                  {microserviceResult.score < 70 && <span style={{ padding: "3px 8px", background: "#9ca3af", color: "#fff", borderRadius: 4, fontSize: 10, fontWeight: 600 }}>DISABLED</span>}
                </label>
                <label style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderRadius: 10,
                  background: conversionDecision === "no" ? "#fef2f2" : "#f8fafc",
                  border: conversionDecision === "no" ? "2px solid #ef4444" : "1px solid #e2e8f0",
                  cursor: "pointer", transition: "all 0.2s ease"
                }} onClick={() => setConversionDecision("no")}>
                  <input type="radio" name="conversionDecision" checked={conversionDecision === "no"} onChange={() => setConversionDecision("no")}
                    style={{ width: 18, height: 18, accentColor: "#ef4444", cursor: "pointer" }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: conversionDecision === "no" ? "#991b1b" : "#475569" }}>No, Keep the existing structure</div>
                    <div style={{ fontSize: 11, color: conversionDecision === "no" ? "#b91c1c" : "#94a3b8", marginTop: 2 }}>Maintain current architecture</div>
                  </div>
                </label>
              </div>

              {conversionDecision === "yes" && microserviceResult.suggested_services && microserviceResult.suggested_services.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#1e40af", marginBottom: 10 }}>🧩 Suggested Microservices Decomposition:</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                    {microserviceResult.suggested_services.map((svc: any, i: number) => (
                      <div key={i} style={{ padding: "12px 16px", background: "#fff", borderRadius: 10, border: "1px solid #bfdbfe", minWidth: 180 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af", marginBottom: 4 }}>{typeof svc === "string" ? svc : svc.name || svc}</div>
                        {typeof svc === "object" && svc.description && <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>{svc.description}</div>}
                        {typeof svc === "object" && svc.components && svc.components.length > 0 && (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                            {svc.components.slice(0, 4).map((comp: string, j: number) => (
                              <span key={j} style={{ padding: "2px 8px", background: "#dbeafe", borderRadius: 4, fontSize: 10, color: "#1e40af" }}>{comp}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Repo Stats */}
            <div style={{ marginTop: 16, display: "flex", gap: 10, flexWrap: "wrap" }}>
              {[
                { label: "Java Files", value: microserviceResult.java_files_count, abbr: "Java", icon: "☕" },
                { label: "Controllers", value: microserviceResult.controllers_count, abbr: "Controllers", icon: "🎮" },
                { label: "Services", value: microserviceResult.services_count, abbr: "Services", icon: "⚙️" },
                { label: "Entities", value: microserviceResult.entities_count, abbr: "Entities", icon: "📦" },
                { label: "Repositories", value: microserviceResult.repositories_count, abbr: "Repositories", icon: "🗄️" }
              ].map((stat, i) => (
                <div key={i} style={{ padding: "6px 12px", background: "#f1f5f9", borderRadius: 6, border: "1px solid #e2e8f0", fontSize: 11, color: "#475569", fontWeight: 500 }}>
                  {stat.icon} {stat.abbr}: <strong>{stat.value ?? 0}</strong>
                </div>
              ))}
            </div>

            {/* Folder Structure */}
            {microserviceResult.eligible && microserviceResult.folder_structure && (
              <div style={{ marginTop: 16 }}>
                <button style={{ ...styles.secondaryBtn, fontSize: 13, padding: "8px 16px", marginBottom: showFolderStructure ? 12 : 0 }}
                  onClick={() => setShowFolderStructure(!showFolderStructure)}>
                  {showFolderStructure ? "[Folder] Hide Folder Structure" : "[Folder] View Recommended Folder Structure"}
                </button>
                {showFolderStructure && (
                  <div style={{ background: "#1e293b", color: "#e2e8f0", padding: "16px 20px", borderRadius: 10, fontSize: 13, fontFamily: "'Fira Code', 'Cascadia Code', 'Consolas', monospace", lineHeight: 1.7, whiteSpace: "pre-wrap", overflowX: "auto", border: "1px solid #334155", maxHeight: 500, overflowY: "auto" }}>
                    {typeof microserviceResult.folder_structure === "string" ? microserviceResult.folder_structure : JSON.stringify(microserviceResult.folder_structure, null, 2)}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
