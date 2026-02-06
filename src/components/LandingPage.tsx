import React from "react";
import Header from "./Header";
import Footer from "./Footer";
import apexLogo from "../assets/apexlogo.png";

export default function LandingPage({ onStart }: { onStart: () => void }) {
  const styles: { [key: string]: React.CSSProperties } = {
    container: {
      minHeight: "100vh",
      backgroundColor: "#0f1419",
      color: "#ffffff",
      display: "flex",
      flexDirection: "column",
      width: "100vw",
      marginLeft: "calc(-50vw + 50%)",
      overflow: "hidden",
    },
    navbar: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "20px 40px",
      borderBottom: "1px solid #1e293b",
      backgroundColor: "rgba(15, 20, 25, 0.95)",
      backdropFilter: "blur(10px)",
    },
    logo: {
      fontSize: 24,
      fontWeight: 700,
      display: "flex",
      alignItems: "center",
      gap: 10,
      color: "#3b82f6",
    },
    navLinks: {
      display: "flex",
      gap: 30,
      alignItems: "center",
    },
    navLink: {
      color: "#e2e8f0",
      textDecoration: "none",
      fontSize: 14,
      fontWeight: 500,
      cursor: "pointer",
      transition: "color 0.3s ease",
    },
    ctaButton: {
      backgroundColor: "#3b82f6",
      color: "#fff",
      padding: "12px 24px",
      borderRadius: 8,
      border: "none",
      fontWeight: 700,
      cursor: "pointer",
      fontSize: 14,
      transition: "all 0.3s ease",
      boxShadow: "0 4px 12px rgba(59, 130, 246, 0.3)",
    },
    hero: {
      flex: 1,
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      alignItems: "center",
      textAlign: "center",
      padding: "60px 40px",
      maxWidth: 1200,
      margin: "0 auto",
      width: "100%",
    },
    headline: {
      fontSize: 64,
      fontWeight: 800,
      marginBottom: 20,
      letterSpacing: "-1px",
      color: "#f8fafc",
    },
    highlightedText: {
      fontSize: 64,
      fontWeight: 800,
      background: "linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%)",
      WebkitBackgroundClip: "text",
      WebkitTextFillColor: "transparent",
      backgroundClip: "text",
      marginBottom: 30,
    },
    description: {
      fontSize: 18,
      color: "#cbd5e1",
      lineHeight: 1.8,
      maxWidth: 700,
      marginBottom: 40,
      fontWeight: 500,
    },
    ctaContainer: {
      display: "flex",
      gap: 20,
      justifyContent: "center",
      marginBottom: 40,
    },
    primaryBtn: {
      backgroundColor: "#3b82f6",
      color: "#fff",
      padding: "16px 40px",
      borderRadius: 8,
      border: "none",
      fontWeight: 700,
      fontSize: 16,
      cursor: "pointer",
      transition: "all 0.3s ease",
      boxShadow: "0 8px 16px rgba(59, 130, 246, 0.4)",
    },
    secondaryBtn: {
      backgroundColor: "transparent",
      color: "#3b82f6",
      padding: "16px 40px",
      borderRadius: 8,
      border: "2px solid #3b82f6",
      fontWeight: 700,
      fontSize: 16,
      cursor: "pointer",
      transition: "all 0.3s ease",
    },
    versionInfo: {
      fontSize: 14,
      color: "#94a3b8",
      marginBottom: 60,
    },
    features: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
      gap: 30,
      width: "100%",
      marginBottom: 60,
    },
    featureCard: {
      padding: 24,
      borderRadius: 12,
      border: "1px solid #1e293b",
      backgroundColor: "rgba(30, 41, 59, 0.3)",
      transition: "all 0.3s ease",
    },
    featureIcon: {
      fontSize: 32,
      marginBottom: 12,
    },
    featureTitle: {
      fontSize: 18,
      fontWeight: 700,
      marginBottom: 10,
      color: "#f8fafc",
    },
    featureDesc: {
      fontSize: 14,
      color: "#cbd5e1",
      lineHeight: 1.6,
    },
    footer: {
      borderTop: "1px solid #1e293b",
      padding: "40px",
      textAlign: "center",
      backgroundColor: "rgba(15, 20, 25, 0.5)",
      fontSize: 14,
      color: "#94a3b8",
    },
    poweredBy: {
      marginTop: 20,
      fontSize: 13,
      color: "#64748b",
    },
  };

  return (
    <div style={styles.container}>
      <Header />

      {/* Hero Section */}
      <div style={styles.hero}>
        <h1 style={styles.headline}>Modernize Your</h1>
        <div style={styles.highlightedText}>Java Applications</div>
        
        <p style={styles.description}>
          Accelerate your Java application migration with automated tools and intelligent refactoring. 
          Upgrade to newer Java versions with minimal effort and maximum reliability. 
          Reduce technical debt and improve performance across your entire codebase.
        </p>

        {/* Features Grid */}
        <div style={styles.features}>
          <div style={styles.featureCard}
            onMouseEnter={(e) => {
              e.currentTarget.style.border = "1px solid #3b82f6";
              e.currentTarget.style.backgroundColor = "rgba(59, 130, 246, 0.1)";
              e.currentTarget.style.transform = "translateY(-4px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.border = "1px solid #1e293b";
              e.currentTarget.style.backgroundColor = "rgba(30, 41, 59, 0.3)";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            <div style={styles.featureIcon}>⚡</div>
            <div style={styles.featureTitle}>Fast Migration</div>
            <div style={styles.featureDesc}>Automated refactoring and code transformation in minutes</div>
          </div>

          <div style={styles.featureCard}
            onMouseEnter={(e) => {
              e.currentTarget.style.border = "1px solid #3b82f6";
              e.currentTarget.style.backgroundColor = "rgba(59, 130, 246, 0.1)";
              e.currentTarget.style.transform = "translateY(-4px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.border = "1px solid #1e293b";
              e.currentTarget.style.backgroundColor = "rgba(30, 41, 59, 0.3)";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            <div style={styles.featureIcon}>🔍</div>
            <div style={styles.featureTitle}>Deep Analysis</div>
            <div style={styles.featureDesc}>Comprehensive dependency and compatibility scanning</div>
          </div>

          <div style={styles.featureCard}
            onMouseEnter={(e) => {
              e.currentTarget.style.border = "1px solid #3b82f6";
              e.currentTarget.style.backgroundColor = "rgba(59, 130, 246, 0.1)";
              e.currentTarget.style.transform = "translateY(-4px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.border = "1px solid #1e293b";
              e.currentTarget.style.backgroundColor = "rgba(30, 41, 59, 0.3)";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            <div style={styles.featureIcon}>✅</div>
            <div style={styles.featureTitle}>Quality Assurance</div>
            <div style={styles.featureDesc}>Automated testing and SonarQube integration included</div>
          </div>
        </div>

        <div style={styles.versionInfo}>Latest Version: 1.0.0</div>

        {/* CTA Buttons */}
        <div style={styles.ctaContainer}>
          <button
            style={styles.primaryBtn}
            onClick={onStart}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = "#2563eb";
              e.currentTarget.style.boxShadow = "0 12px 24px rgba(59, 130, 246, 0.5)";
              e.currentTarget.style.transform = "translateY(-2px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = "#3b82f6";
              e.currentTarget.style.boxShadow = "0 8px 16px rgba(59, 130, 246, 0.4)";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            Start Migration →
          </button>
          <button
            style={styles.secondaryBtn}
            onClick={() => {
              window.location.href = 'http://localhost:8001/api/auth/github/login';
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = "rgba(59, 130, 246, 0.1)";
              e.currentTarget.style.transform = "translateY(-2px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = "transparent";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            Login with GitHub
          </button>
          <button
            style={styles.secondaryBtn}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = "rgba(59, 130, 246, 0.1)";
              e.currentTarget.style.transform = "translateY(-2px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = "transparent";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            About this product
          </button>
        </div>
      </div>

      <Footer />
    </div>
  );
}
