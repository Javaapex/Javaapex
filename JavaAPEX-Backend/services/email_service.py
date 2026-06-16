"""
Email Service - Send migration summary emails
"""
import logging
import os
from typing import Any
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.email_from = os.getenv("EMAIL_FROM", "migration-bot@example.com")
    
    async def send_migration_summary(self, to_email: str, job: Any) -> bool:
        """Send migration summary email"""
        try:
            logger.info(
                "Preparing migration summary email recipient=%s smtp_host=%s smtp_port=%s smtp_configured=%s",
                to_email,
                self.smtp_host,
                self.smtp_port,
                bool(self.smtp_user and self.smtp_password and self.smtp_password != "your_app_password_here"),
            )

            # Generate email content
            subject = f"Migration Complete: {job.source_repo} → Java {job.target_java_version}"
            html_content = self._generate_email_html(job)
            text_content = self._generate_email_text(job)

            logger.debug("Generated migration summary email subject=%s", subject)

            # Create message
            message = MIMEMultipart("alternative")
            message["From"] = self.email_from
            message["To"] = to_email
            message["Subject"] = subject

            message.attach(MIMEText(text_content, "plain"))
            message.attach(MIMEText(html_content, "html"))

            # Send email
            if self.smtp_user and self.smtp_password and self.smtp_password != "your_app_password_here":
                logger.info("Sending migration summary email via SMTP recipient=%s", to_email)
                await aiosmtplib.send(
                    message,
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    username=self.smtp_user,
                    password=self.smtp_password,
                    start_tls=True
                )
                logger.info("Migration summary email sent successfully recipient=%s", to_email)
                return True
            else:
                logger.warning(
                    "SMTP credentials not configured; skipping email send recipient=%s subject=%s content_chars=%s",
                    to_email,
                    subject,
                    len(text_content),
                )
                return False  # Return False so we know it didn't actually send

        except Exception as e:
            logger.exception("Failed to send migration summary email recipient=%s", to_email)
            return False
    
    def _generate_email_html(self, job: Any) -> str:
        """Generate HTML email content"""
        template = Template("""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #007bff; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
        .content { background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }
        .section { margin-bottom: 20px; }
        .section h3 { color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 5px; }
        .stat { display: inline-block; margin: 10px 20px 10px 0; }
        .stat-value { font-size: 24px; font-weight: bold; color: #28a745; }
        .stat-label { font-size: 12px; color: #666; }
        .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
        .badge-success { background: #28a745; color: white; }
        .badge-warning { background: #ffc107; color: black; }
        .badge-danger { background: #dc3545; color: white; }
        .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f0f0f0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Migration Complete!</h1>
            <p>Java {{ source_version }} → Java {{ target_version }}</p>
        </div>
        
        <div class="content">
            <div class="section">
                <h3>📊 Migration Summary</h3>
                <div class="stat">
                    <div class="stat-value">{{ files_modified }}</div>
                    <div class="stat-label">Files Modified</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ issues_fixed }}</div>
                    <div class="stat-label">Issues Fixed</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ api_working }}/{{ api_total }}</div>
                    <div class="stat-label">APIs Working</div>
                </div>
            </div>
            
            <div class="section">
                <h3>🔍 Code Quality (SonarQube)</h3>
                <p>Quality Gate: <span class="badge badge-success">{{ quality_gate }}</span></p>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Bugs</td><td>{{ bugs }}</td></tr>
                    <tr><td>Vulnerabilities</td><td>{{ vulnerabilities }}</td></tr>
                    <tr><td>Code Smells</td><td>{{ code_smells }}</td></tr>
                    <tr><td>Coverage</td><td>{{ coverage }}%</td></tr>
                </table>
            </div>
            
            <div class="section">
                <h3>🔗 Repository Links</h3>
                <p><strong>Source:</strong> <a href="{{ source_repo }}">{{ source_repo }}</a></p>
                <p><strong>Migrated:</strong> <a href="{{ target_repo }}">{{ target_repo }}</a></p>
            </div>
            
            <div class="section">
                <h3>📦 Dependencies Updated</h3>
                <table>
                    <tr><th>Artifact</th><th>Old Version</th><th>New Version</th><th>Status</th></tr>
                    {% for dep in dependencies %}
                    <tr>
                        <td>{{ dep.artifact_id }}</td>
                        <td>{{ dep.current_version }}</td>
                        <td>{{ dep.new_version or 'N/A' }}</td>
                        <td><span class="badge badge-{{ 'success' if dep.status == 'upgraded' else 'warning' }}">{{ dep.status }}</span></td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
        
        <div class="footer">
            <p>Generated by Javtion) tara Migration Accelerator</p>
            <p>{{ timestamp }}</p>
        </div>
    </div>
</body>
</html>
        """)
        
        return template.render(
            source_version=job.source_java_version,
            target_version=job.target_java_version,
            files_modified=job.files_modified,
            issues_fixed=job.issues_fixed,
            api_working=job.api_endpoints_working,
            api_total=job.api_endpoints_validated,
            quality_gate=job.sonar_quality_gate or "N/A",
            bugs=job.sonar_bugs,
            vulnerabilities=job.sonar_vulnerabilities,
            code_smells=job.sonar_code_smells,
            coverage=job.sonar_coverage,
            source_repo=job.source_repo,
            target_repo=job.target_repo or "Pending",
            dependencies=job.dependencies[:10] if job.dependencies else [],
            timestamp=job.completed_at.isoformat() if job.completed_at else "In Progress"
        )
    
    def _generate_email_text(self, job: Any) -> str:
        """Generate plain text email content"""
        return f"""
Java Migration Complete!
========================

Migration: Java {job.source_java_version} → Java {job.target_java_version}

Summary:
- Files Modified: {job.files_modified}
- Issues Fixed: {job.issues_fixed}
- APIs Working: {job.api_endpoints_working}/{job.api_endpoints_validated}

Code Quality (SonarQube):
- Quality Gate: {job.sonar_quality_gate or 'N/A'}
- Bugs: {job.sonar_bugs}
- Vulnerabilities: {job.sonar_vulnerabilities}
- Code Smells: {job.sonar_code_smells}
- Coverage: {job.sonar_coverage}%

Repository Links:
- Source: {job.source_repo}
- Migrated: {job.target_repo or 'Pending'}

---
Generated by Java Migration Accelerator
        """
