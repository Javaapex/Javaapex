import React from "react";

const stepStyles: { [key: string]: React.CSSProperties } = {
  root: {
    display: "flex",
    gap: 20,
    marginBottom: 28,
    marginTop: 20,
  },
  card: {
    flex: 1,
    background: "#f8fafc",
    borderRadius: 10,
    padding: "20px 0",
    textAlign: "center",
    fontWeight: 500,
    fontSize: 15,
    color: "#334155",
    boxShadow: "0 1px 6px rgba(0,0,0,0.04)",
    border: "1.5px solid #e0e0e0",
    transition: "border 0.2s, background 0.2s",
  },
  cardActive: {
    background: "#2563eb",
    color: "#fff",
    border: "1.5px solid #2563eb",
    boxShadow: "0 2px 12px rgba(37,99,235,0.08)",
  },
  stepNum: {
    display: "block",
    fontSize: 13,
    fontWeight: 700,
    marginBottom: 6,
    opacity: 0.7,
  },
};

const steps = [
  { label: "Select source system", icon: "📁" },
  { label: "Select target system", icon: "☁️" },
  { label: "Finalize", icon: "⚙️" },
];

const StepCards: React.FC<{ current: number }> = ({ current }) => (
  <div style={stepStyles.root}>
    {steps.map((step, idx) => (
      <div
        key={step.label}
        style={{
          ...stepStyles.card,
          ...(current === idx + 1 ? stepStyles.cardActive : {}),
        }}
      >
        <span style={stepStyles.stepNum}>{step.icon} Step {idx + 1}</span>
        {step.label}
      </div>
    ))}
  </div>
);

export default StepCards;
