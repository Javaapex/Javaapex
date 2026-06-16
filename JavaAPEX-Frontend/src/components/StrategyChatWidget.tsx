import React, { useEffect, useId, useRef, useState } from "react";
import type { StrategyPageContext } from "../services/api";
import { API_BASE_URL } from "../services/api";

type Role = "user" | "assistant" | "system";

interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  rationale?: string[];
  comparisonTable?: ComparisonTableSpec | null;
  details?: Record<string, unknown> | null;
  createdAt: string;
}

interface ComparisonTableSpec {
  caption?: string;
  headers: string[];
  rows: string[][];
}

type ContentBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "table"; table: ComparisonTableSpec };

interface Props {
  repoUrl?: string | null;
  strategyContext?: StrategyPageContext | null;
}

const STORAGE_KEY_PREFIX = "javaapex_strategy_chat_v1";

function makeStorageKey(repoUrl?: string | null) {
  const repoId = repoUrl ? repoUrl.replace(/[^a-z0-9-_]/gi, "_") : "global";
  return `${STORAGE_KEY_PREFIX}_${repoId}`;
}

export default function StrategyChatWidget({ repoUrl, strategyContext }: Props) {
  const assistantName = "JavaApex Assistant";

  const AssistantLogo: React.FC<{ size?: number; className?: string }> = ({ size = 46, className }) => {
    const idSuffix = useId().replace(/:/g, "");
    const orbId = `assistant_orb_${idSuffix}`;
    const glowId = `assistant_glow_${idSuffix}`;
    const sparkleId = `assistant_sparkle_${idSuffix}`;

    return (
      <svg
        className={className}
        width={size}
        height={size}
        viewBox="0 0 96 96"
        fill="none"
        aria-hidden
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <radialGradient id={orbId} cx="0.28" cy="0.22" r="0.92">
            <stop offset="0" stopColor="#FF8BE8" />
            <stop offset="0.34" stopColor="#C66BFF" />
            <stop offset="0.68" stopColor="#6484FF" />
            <stop offset="1" stopColor="#2A86FF" />
          </radialGradient>
          <radialGradient id={glowId} cx="0.34" cy="0.28" r="0.8">
            <stop offset="0" stopColor="#FFFFFF" stopOpacity="1" />
            <stop offset="0.38" stopColor="#FFFFFF" stopOpacity="0.52" />
            <stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
          </radialGradient>
          <linearGradient id={sparkleId} x1="28" y1="28" x2="68" y2="68" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#FFFFFF" />
            <stop offset="1" stopColor="#FFFFFF" stopOpacity="0.92" />
          </linearGradient>
        </defs>
        <circle cx="48" cy="48" r="39" fill={`url(#${orbId})`} />
        <circle cx="48" cy="48" r="31" fill={`url(#${glowId})`} opacity="0.95" />
        <circle cx="38" cy="32" r="11" fill="#FFFFFF" opacity="0.18" />
        <circle cx="61" cy="62" r="9" fill="#FFFFFF" opacity="0.1" />
        <path
          d="M48 25.5c1.2 3.2 2.7 5.4 4.8 6.6 2.1 1.2 4.4 1.8 7 1.8-2.6 0-4.9.6-7 1.8-2.1 1.2-3.6 3.4-4.8 6.6-1.2-3.2-2.7-5.4-4.8-6.6-2.1-1.2-4.4-1.8-7-1.8 2.6 0 4.9-.6 7-1.8 2.1-1.2 3.6-3.4 4.8-6.6Z"
          fill={`url(#${sparkleId})`}
          opacity="0.98"
        />
        <path
          d="M34.5 40.5c.9 2.3 1.9 3.9 3.4 4.8 1.5.8 3.1 1.2 5 1.2-1.9 0-3.5.4-5 1.2-1.5.8-2.5 2.4-3.4 4.8-.9-2.3-1.9-3.9-3.4-4.8-1.5-.8-3.1-1.2-5-1.2 1.9 0 3.5-.4 5-1.2 1.5-.8 2.5-2.4 3.4-4.8Z"
          fill={`url(#${sparkleId})`}
          opacity="0.95"
        />
        <path
          d="M52.2 46.2c.5 1.2 1 2 1.8 2.5.8.4 1.7.6 2.7.6-1 0-1.9.2-2.7.6-.8.5-1.3 1.3-1.8 2.5-.5-1.2-1-2-1.8-2.5-.8-.4-1.7-.6-2.7-.6 1 0 1.9-.2 2.7-.6.8-.5 1.3-1.3 1.8-2.5Z"
          fill={`url(#${sparkleId})`}
          opacity="1"
        />
      </svg>
    );
  };

  // Rotating descriptive messages for the answer phase
  const AnimatedRetrieving: React.FC = () => {
    const messages = [
      "Reading strategy page",
      "Using page context",
      "Preparing answer",
    ];
    const [idx, setIdx] = useState(0);
    useEffect(() => {
      const t = setInterval(() => setIdx((i) => (i + 1) % messages.length), 800);
      return () => clearInterval(t);
    }, []);
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
          <circle cx="12" cy="12" r="10" stroke="#93c5fd" strokeWidth="2" opacity="0.18" />
          <path d="M22 12a10 10 0 0 0-10-10" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <span style={{ color: "#475569" }}>{messages[idx]}</span>
      </span>
    );
  };
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [hovered, setHovered] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const abortedByUserRef = useRef(false);
  const activeRepoName = strategyContext?.repository?.name || repoUrl || "this repository";

  const storageKey = makeStorageKey(repoUrl);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) setMessages(JSON.parse(raw));
    } catch {
      // ignore
    }
  }, [storageKey]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(messages));
    } catch {
      // ignore
    }
  }, [messages, storageKey]);

  useEffect(() => {
    if (open && panelRef.current) {
      const el = panelRef.current;
      // scroll to bottom
      setTimeout(() => {
        el.scrollTop = el.scrollHeight;
      }, 50);
    }
  }, [open, messages]);

  // persist lastSeenAt when panel opens or messages are read
  

  const addMessage = (msg: ChatMessage) => setMessages((m) => [...m, msg]);

  const focusComposer = () => {
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const normalizeComparisonTable = (value: unknown): ComparisonTableSpec | null => {
    if (!value || typeof value !== "object") return null;
    const candidate = value as Record<string, unknown>;
    const headers = Array.isArray(candidate.headers)
      ? candidate.headers.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : [];
    const rows = Array.isArray(candidate.rows)
      ? candidate.rows
          .map((row) =>
            Array.isArray(row)
              ? row.filter((item): item is string => typeof item === "string").map((item) => item.trim())
              : []
          )
          .filter((row) => row.length > 0)
      : [];
    if (headers.length < 2 || rows.length === 0) return null;
    return {
      caption: typeof candidate.caption === "string" ? candidate.caption : undefined,
      headers,
      rows,
    };
  };

  const isMarkdownTableDivider = (line: string) =>
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);

  const splitMarkdownTableRow = (line: string) =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((part) => part.trim());

  const renderInlineMarkdown = (text: string) => {
    const segments = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
    return segments.map((segment, segmentIndex) => {
      if (segment.startsWith("**") && segment.endsWith("**") && segment.length > 4) {
        return (
          <strong key={`${segmentIndex}_${segment}`} className="strategy-chat-inline-strong">
            {segment.slice(2, -2)}
          </strong>
        );
      }
      if (segment.startsWith("`") && segment.endsWith("`") && segment.length > 2) {
        return (
          <code key={`${segmentIndex}_${segment}`} className="strategy-chat-inline-code">
            {segment.slice(1, -1)}
          </code>
        );
      }
      return <React.Fragment key={`${segmentIndex}_${segment}`}>{segment}</React.Fragment>;
    });
  };

  const parseMarkdownContentBlocks = (content: string): ContentBlock[] => {
    const lines = (content || "").replace(/\r\n/g, "\n").split("\n");
    const blocks: ContentBlock[] = [];
    const paragraphLines: string[] = [];
    let index = 0;

    const flushParagraph = () => {
      const text = paragraphLines.join("\n").trim();
      if (text) {
        blocks.push({ kind: "paragraph", text });
      }
      paragraphLines.length = 0;
    };

    while (index < lines.length) {
      const line = lines[index] || "";
      const nextLine = lines[index + 1] || "";

      if (!line.trim()) {
        flushParagraph();
        index += 1;
        continue;
      }

      if (line.includes("|") && isMarkdownTableDivider(nextLine)) {
        flushParagraph();
        const headers = splitMarkdownTableRow(line);
        const rows: string[][] = [];
        index += 2;

        while (index < lines.length) {
          const rowLine = lines[index] || "";
          if (!rowLine.trim() || !rowLine.includes("|")) {
            break;
          }
          const cells = splitMarkdownTableRow(rowLine);
          if (cells.length > 1) {
            rows.push(cells);
          }
          index += 1;
        }

        if (headers.length > 1 && rows.length > 0) {
          const columnCount = Math.max(headers.length, ...rows.map((row) => row.length));
          blocks.push({
            kind: "table",
            table: {
              headers: headers.slice(0, columnCount),
              rows: rows.map((row) =>
                Array.from({ length: columnCount }, (_, colIndex) => row[colIndex] || "")
              ),
            },
          });
        }
        continue;
      }

      paragraphLines.push(line);
      index += 1;
    }

    flushParagraph();
    return blocks;
  };

  const renderAssistantContent = (message: ChatMessage) => {
    const blocks = parseMarkdownContentBlocks(message.content || "");
    const hasMarkdownTable = blocks.some((block) => block.kind === "table");
    const elements: React.ReactNode[] = [];

    blocks.forEach((block, blockIndex) => {
      if (block.kind === "paragraph") {
        elements.push(
          <div key={`${message.id}_p_${blockIndex}`} className="strategy-chat-rich-text">
            {renderInlineMarkdown(block.text)}
          </div>
        );
        return;
      }

      const blockColumnCount = Math.max(
        block.table.headers.length,
        ...block.table.rows.map((row) => row.length)
      );

      elements.push(
        <div key={`${message.id}_t_${blockIndex}`} className="strategy-chat-table-wrap">
          <table className="strategy-chat-table">
            <thead>
              <tr>
                {Array.from({ length: blockColumnCount }, (_, headerIndex) => (
                  <th key={`${message.id}_th_${blockIndex}_${headerIndex}`}>
                    {block.table.headers[headerIndex] || ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.table.rows.map((row, rowIndex) => (
                <tr key={`${message.id}_tr_${blockIndex}_${rowIndex}`}>
                  {Array.from({ length: blockColumnCount }, (_, colIndex) => (
                    <td key={`${message.id}_td_${blockIndex}_${rowIndex}_${colIndex}`}>
                      {row[colIndex] || ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    });

    if (!hasMarkdownTable && message.comparisonTable) {
      const columnCount = Math.max(
        message.comparisonTable.headers.length,
        ...message.comparisonTable.rows.map((row) => row.length)
      );
      elements.push(
        <div key={`${message.id}_comparison`} className="strategy-chat-table-wrap">
          {message.comparisonTable.caption && (
            <div className="strategy-chat-table-caption">{message.comparisonTable.caption}</div>
          )}
          <table className="strategy-chat-table">
            <thead>
              <tr>
                {Array.from({ length: columnCount }, (_, headerIndex) => (
                  <th key={`${message.id}_c_th_${headerIndex}`}>
                    {message.comparisonTable.headers[headerIndex] || ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {message.comparisonTable.rows.map((row, rowIndex) => (
                <tr key={`${message.id}_c_tr_${rowIndex}`}>
                  {Array.from({ length: columnCount }, (_, colIndex) => (
                    <td key={`${message.id}_c_td_${rowIndex}_${colIndex}`}>
                      {row[colIndex] || ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    return elements.length > 0 ? elements : [<div key={`${message.id}_empty`}>{message.content || "..."}</div>];
  };

  const handleSend = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text) return;
    const userMsg: ChatMessage = {
      id: `u_${Date.now()}`,
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    addMessage(userMsg);
    setInput("");
    setOpen(true);
    setSending(true);

    const assistantPlaceholder: ChatMessage = {
      id: `a_${Date.now()}`,
      role: "assistant",
      content: "",
      createdAt: new Date().toISOString(),
    };
    addMessage(assistantPlaceholder);

    try {
      // Use POST streaming endpoint that emits SSE-like events
      const url = `${API_BASE_URL}/strategy/query/stream`;
      const controller = new AbortController();
      abortControllerRef.current = controller;
      abortedByUserRef.current = false;
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_url: repoUrl || undefined,
          question: text,
          strategy_context: strategyContext || undefined,
        }),
        signal: controller.signal,
      });

      if (!resp.ok || !resp.body) {
        // fallback to non-streaming if available
        throw new Error(`Streaming request failed: ${resp.status} ${resp.statusText}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      const flushEvent = (raw: string) => {
        const lines = raw.split("\n");
        let event: string | null = null;
        const dataLines: string[] = [];
        for (const ln of lines) {
          if (ln.startsWith("event:")) {
            event = ln.replace(/^event:\s*/, "").trim();
          } else if (ln.startsWith("data:")) {
            dataLines.push(ln.replace(/^data:\s*/, ""));
          }
        }
        if (dataLines.length === 0) return;
        try {
          const payload = JSON.parse(dataLines.join("\n"));
          if (event === "phase") {
            const msg = payload?.message || payload?.phase || "...";
            setMessages((prev) => prev.map((m) => (m.id === assistantPlaceholder.id ? { ...m, content: msg } : m)));
          } else if (event === "chunk") {
            const chunk = payload?.chunk || payload?.text || "";
            if (chunk) {
              setMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== assistantPlaceholder.id) return m;
                  const phaseStates = ["Reading strategy page", "Using page context", "Preparing answer"];
                  const current = (m.content || "").toString();
                  const base = phaseStates.includes(current) ? "" : current;
                  return { ...m, content: `${base}${chunk}`.replace(/\s{2,}/g, " ") };
                })
              );
            }
          } else if (event === "final") {
            const parsed = payload?.parsed || {};
            const details = payload?.details || {};
            const answer = parsed.answer || payload?.parsed?.answer || payload?.answer || "";
            const rationale = parsed.rationale || parsed.reasons || [];
            const comparisonTable = normalizeComparisonTable(details?.comparison_table || parsed?.comparison_table);
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== assistantPlaceholder.id) return m;
                // Preserve streamed content if it's longer and non-empty
                const phaseStates = ["Reading strategy page", "Using page context", "Preparing answer"];
                const current = (m.content || "").toString();
                const isPhase = phaseStates.includes(current);
                const finalContent = answer
                  ? ((!isPhase && current.length > answer.length) ? current : answer)
                  : (isPhase ? "..." : current || "...");
                return {
                  ...m,
                  content: finalContent,
                  rationale,
                  comparisonTable,
                  details: {
                    ...(details as Record<string, unknown>),
                    parsed,
                    comparison_table: comparisonTable,
                  },
                };
              })
            );
          } else if (event === "error") {
            const errMsg = payload?.message || JSON.stringify(payload);
            setMessages((prev) => prev.map((m) => (m.id === assistantPlaceholder.id ? { ...m, content: `Error: ${errMsg}` } : m)));
          }
        } catch (e) {
          // ignore parse errors
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx = buffer.indexOf("\n\n");
        while (idx !== -1) {
          const raw = buffer.slice(0, idx).trim();
          if (raw) flushEvent(raw);
          buffer = buffer.slice(idx + 2);
          idx = buffer.indexOf("\n\n");
        }
      }

      // flush remaining
      if (buffer.trim()) flushEvent(buffer.trim());
    } catch (err: any) {
      // handle abort vs other errors
      const aborted = abortedByUserRef.current || (err && err.name === "AbortError");
      if (aborted) {
        const stopText = `Stopped by user.`;
        setMessages((prev) => prev.map((m) => (m.id === assistantPlaceholder.id ? { ...m, content: stopText } : m)));
      } else {
        const errorText = `Error: ${err?.message || String(err)}`;
        setMessages((prev) => prev.map((m) => (m.id === assistantPlaceholder.id ? { ...m, content: errorText } : m)));
      }
    } finally {
      setSending(false);
      try {
        abortControllerRef.current = null;
        abortedByUserRef.current = false;
      } catch {}
    }
  };

  const handleStop = () => {
    const ctrl = abortControllerRef.current;
    if (ctrl) {
      abortedByUserRef.current = true;
      try {
        ctrl.abort();
      } catch {}
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      // Press Enter to send, Shift+Enter for newline
      e.preventDefault();
      void handleSend();
    }
  };

  const usePrompt = (prompt: string) => {
    setOpen(true);
    void handleSend(prompt);
  };

  const clearHistory = () => {
    setMessages([]);
    try {
      localStorage.removeItem(storageKey);
    } catch {}
  };

  const hasMessages = messages.length > 0;
  const latestAssistantMessage = [...messages].reverse().find((message) => message.role === "assistant");
  const showingTypingState =
    sending ||
    ["Reading strategy page", "Using page context", "Preparing answer"].includes(
      (latestAssistantMessage?.content || "").toString()
    );

  return (
    <div>
      {/* Floating button */}
      <button
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        aria-label="Open strategy chat"
        title="Open JavaApex Assistant"
        style={{
          position: "fixed",
          right: 20,
          bottom: 20,
          width: 56,
          height: 56,
          borderRadius: 28,
          background: "transparent",
          border: "none",
          boxShadow: hovered ? "0 10px 30px rgba(2,6,23,0.28)" : "0 6px 20px rgba(2,6,23,0.2)",
          cursor: "pointer",
          zIndex: 1100,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "transform 160ms ease, box-shadow 160ms ease",
          transform: hovered ? "scale(1.06) rotate(-6deg)" : "none",
          padding: 0,
        }}
      >
        <AssistantLogo size={34} />
      </button>

      {/* Chat panel */}
      {open && (
        <div
          ref={panelRef}
          className="strategy-chat-panel"
          style={{
            position: "fixed",
            right: 20,
            left: "auto",
            bottom: 90,
            top: "auto",
            width: 470,
            height: undefined,
            maxHeight: "82vh",
            zIndex: 1100,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          <div className="strategy-chat-header">
            <div className="strategy-chat-brand">
              <div className="strategy-chat-avatar" aria-hidden>
                <AssistantLogo size={54} className="strategy-chat-avatar-image" />
              </div>
              <div style={{ minWidth: 0 }}>
                <div className="strategy-chat-title">{assistantName}</div>
              </div>
            </div>
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              <button onClick={clearHistory} title="Clear history" style={{ border: "none", background: "transparent", cursor: "pointer", color: "#6b7280", padding: 6 }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M3 6h18" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M8 6v12a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V6" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M10 11v6" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M14 11v6" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </button>
              <button onClick={() => setOpen(false)} title="Close" style={{ border: "none", background: "transparent", cursor: "pointer", color: "#6b7280", padding: 6 }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M18 6L6 18M6 6l12 12" stroke="#6b7280" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </button>
            </div>
          </div>

          <div className="strategy-chat-body">
            <div className="strategy-chat-canvas">
              {showingTypingState && (
                <div className="strategy-chat-status">
                  <span className="strategy-chat-status-spinner" aria-hidden>
                    <span />
                  </span>
                  <span>Analyzing data, please wait...</span>
                </div>
              )}

              {messages.length === 0 ? (
                <div className="strategy-chat-empty-state" aria-live="polite">
                  <div className="strategy-chat-empty-state-badge">Chat ready</div>
                </div>
              ) : (
                <div className="strategy-chat-messages">
                  {messages.map((m) => (
                    <div
                      key={m.id}
                      className={`strategy-chat-row ${m.role === "user" ? "strategy-chat-row-user" : "strategy-chat-row-assistant"}`}
                    >
                      <div className="strategy-chat-message-stack">
                        <div
                          className={`strategy-chat-bubble ${
                            m.role === "user" ? "strategy-chat-bubble-user" : "strategy-chat-bubble-assistant"
                          }`}
                        >
                          {m.role === "assistant" &&
                          ["Reading strategy page", "Using page context", "Preparing answer"].includes((m.content || "").toString()) ? (
                            <AnimatedRetrieving />
                          ) : (
                            m.role === "assistant" ? renderAssistantContent(m) : m.content || ""
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="strategy-chat-composer-shell">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (sending) {
                  handleStop();
                } else {
                  void handleSend();
                }
              }}
              className="strategy-chat-composer"
            >
              <textarea
                ref={textareaRef}
                placeholder="Ask your queries"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={2}
                className="strategy-chat-input"
              />
              <button
                type="submit"
                className={`strategy-chat-send ${sending ? "strategy-chat-send-stop" : ""}`}
                aria-label={sending ? "Stop generation" : "Send question"}
                title={sending ? "Stop generation" : "Send question"}
              >
                {sending ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <rect x="7" y="7" width="10" height="10" rx="2.2" fill="currentColor" />
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M5 12h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                    <path d="m12 5 7 7-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
