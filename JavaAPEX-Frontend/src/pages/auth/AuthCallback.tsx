import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { exchangeGithubAuthCode } from "../../services/api";

const AuthCallback: React.FC = () => {
  const navigate = useNavigate();

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get("code");
    if (code) {
      exchangeGithubAuthCode(code)
        .then((data) => {
          if (data.access_token) {
            localStorage.setItem("github_token", data.access_token);
            localStorage.setItem("github_user", JSON.stringify(data.user));
            navigate("/");
          } else {
            alert("GitHub login failed: " + (data.error || "Unknown error"));
            navigate("/");
          }
        })
        .catch(() => {
          alert("GitHub login failed: Network error");
          navigate("/");
        });
    } else {
      alert("No code found in URL");
      navigate("/");
    }
  }, [navigate]);

  return <div>Logging in with GitHub...</div>;
};

export default AuthCallback;
