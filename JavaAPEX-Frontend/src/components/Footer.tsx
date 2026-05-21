import React from "react";

export default function Footer() {
  const styles: { [key: string]: React.CSSProperties } = {
    footer: {
      borderTop: "1px solid #1e293b",
      padding: "32px 40px",
      textAlign: "center",
      backgroundColor: "rgba(15, 20, 25, 0.5)",
      fontSize: 14,
      color: "#94a3b8",
    },
    copyright: {
      marginBottom: 12,
    },
    poweredBy: {
      fontSize: 13,
      color: "#64748b",
      marginTop: 12,
    },
    sorimai: {
      color: "#3b82f6",
      fontWeight: 700,
    },
  };

  return (
    <footer style={styles.footer}>
      <div style={styles.copyright}>© 2026 javaAPEX. All rights reserved.</div>
      <div style={styles.poweredBy}>
        Powered by <span style={styles.sorimai}>Sorim.ai</span>
      </div>
    </footer>
  );
}
