import React from "react";
import apexLogo from "../../assets/apexlogo.png";

interface HeaderProps {
  showBackButton?: boolean;
  onBackToHome?: () => void;
}

export default function Header({ showBackButton = false, onBackToHome }: HeaderProps) {
  const styles: { [key: string]: React.CSSProperties } = {
    navbar: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "12px 40px",
      borderBottom: "1px solid #1e293b",
      backgroundColor: "rgba(15, 20, 25, 0.95)",
      backdropFilter: "blur(10px)",
      position: "relative",
    },
    logoContainer: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      cursor: "pointer",
    },
    logoText: {
      fontSize: 16,
      fontWeight: 700,
      color: "#3b82f6",
      margin: 0,
    },
    navLinks: {
      display: "flex",
      gap: 20,
      alignItems: "center",
    },
    navLink: {
      color: "#e2e8f0",
      textDecoration: "none",
      fontSize: 13,
      fontWeight: 500,
      cursor: "pointer",
      transition: "color 0.3s ease",
      display: "flex",
      alignItems: "center",
      gap: 6,
    },
    iconButton: {
      width: 34,
      height: 34,
      borderRadius: "50%",
      backgroundColor: "transparent",
      color: "#e2e8f0",
      border: "1px solid #374151",
      cursor: "pointer",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: 14,
      transition: "all 0.3s ease",
    },
    backButton: {
      backgroundColor: "#f1f5f9",
      color: "#1e293b",
      border: "1.5px solid #cbd5e1",
      borderRadius: 8,
      padding: "8px 16px",
      fontWeight: 600,
      cursor: "pointer",
      fontSize: 13,
      transition: "all 0.3s ease",
    },
  };

  return (
    <nav style={styles.navbar}>
      {/* Logo Only - No Text */}
      <div style={styles.logoContainer} onClick={onBackToHome}>
        <img src={apexLogo} alt="javaAPEX" style={{ width: 36, height: 36, objectFit: 'contain' }} />
        <p style={styles.logoText}>javaAPEX</p>
      </div>

      {/* Navigation Links */}
      <div style={styles.navLinks}>
        <a
          style={styles.navLink}
          className="ui-dark-link"
          href="#"
        >
          Documentation
        </a>
        <a
          style={styles.navLink}
          className="ui-dark-link"
          href="https://github.com/sorimdevs-tech/java-migration-accelerator"
          target="_blank"
          rel="noreferrer"
        >
          GitHub
        </a>
        <a
          style={styles.navLink}
          className="ui-dark-link"
          href="#"
        >
          Support Us
        </a>
        
        {showBackButton && onBackToHome ? (
          <button
            style={styles.backButton}
            className="ui-soft-button"
            onClick={onBackToHome}
          >
            ← Home
          </button>
        ) : null}
        
        {/* Profile Icon */}
        <button
          style={styles.iconButton}
          className="ui-dark-icon-button"
          title="Profile"
        >
          👤
        </button>
      </div>
    </nav>
  );
}
