import React, { useState } from "react";
import { queryStrategy } from "../../../services/api";
import type { StrategyAnswerResponse, RepoAnalysis } from "../../../services/api";

interface Props {
  repoAnalysis?: RepoAnalysis | null;
  repoUrl?: string | null;
}

export default function StrategyPrompt({ repoAnalysis, repoUrl }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<StrategyAnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!question || question.trim().length < 3) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const res = await queryStrategy({ repo_url: repoUrl || undefined, question: question.trim(), analysis: repoAnalysis || undefined });
      setResponse(res);
    } catch (err: any) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ marginTop: 18, padding: 16, borderRadius: 12, background: "#ffffff", border: "1px solid #e6eef8" }}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>Ask about this repository</div>
      <div style={{ color: "#475569", marginBottom: 12 }}>Ask questions about vulnerabilities, recommended Java version, ETA estimates, or other findings.</div>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, alignItems: "flex-start", flexDirection: "column" }}>
        <textarea
          placeholder="e.g. How many vulnerabilities were found? Recommend a target Java version? How long will migration take?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #dbe8f8", fontSize: 14 }}
        />
        <div style={{ display: "flex", gap: 8, width: "100%" }}>
          <button type="submit" disabled={loading} style={{ padding: "8px 14px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 8 }}>
            {loading ? "Thinking..." : "Ask"}
          </button>
          <button type="button" onClick={() => { setQuestion(""); setResponse(null); setError(null); }} style={{ padding: "8px 14px", background: "#f3f4f6", border: "none", borderRadius: 8 }}>
            Clear
          </button>
        </div>
      </form>

      {error && <div style={{ marginTop: 12, color: "#dc2626" }}>{error}</div>}

      {response && (
        <div style={{ marginTop: 12, padding: 12, borderRadius: 8, background: "#f8fafc", border: "1px solid #e6eef8" }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Answer</div>
          <div style={{ color: "#0f172a", marginBottom: 8 }}>{response.answer}</div>
          {response.rationale && response.rationale.length > 0 && (
            <div style={{ color: "#475569", fontSize: 13 }}>
              <div style={{ fontWeight: 700 }}>Rationale</div>
              <ul>
                {response.rationale.map((r, idx) => (
                  <li key={idx}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
