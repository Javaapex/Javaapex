"""
AI Service with Ford LLM Integration (formerly Hugging Face)
Provides advanced code analysis using Ford's internal LLM API.
Falls back to Hugging Face if Ford LLM is not configured.
"""
import os
import json
import logging
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, asdict
from datetime import datetime
import re
from utils.config import (
    FORD_LLM_API_ENDPOINT,
    FORD_LLM_API_KEY,
    FORD_LLM_AUTH_TYPE,
    FORD_LLM_ENABLED,
    FORD_LLM_EXTRA_MODELS,
    FORD_LLM_MAX_TOKENS,
    FORD_LLM_MODEL,
    FORD_LLM_PROXY_URL,
    FORD_LLM_TEMPERATURE,
    FORD_LLM_TIMEOUT,
    FORD_LLM_VERIFY_SSL,
    HF_BUSINESS_LOGIC_MODEL,
    HF_CODE_ANALYSIS_MODEL,
    HF_CODE_QUALITY_MODEL,
    HF_GENERAL_MODEL,
    HUGGINGFACE_API_KEY,
    HUGGINGFACE_INFERENCE_BASE_URL,
    httpx_proxy_kwargs as _proxy_kw,
)

logger = logging.getLogger(__name__)

# Hugging Face API Configuration (legacy fallback)
HUGGINGFACE_API_URL = HUGGINGFACE_INFERENCE_BASE_URL

# Model IDs for different analysis types
MODELS = {
    "code_analysis": HF_CODE_ANALYSIS_MODEL,  # For code analysis
    "business_logic": HF_BUSINESS_LOGIC_MODEL,  # For business logic understanding
    "code_quality": HF_CODE_QUALITY_MODEL,  # For code quality
    "general": HF_GENERAL_MODEL,  # General purpose
}


@dataclass
class AIAnalysisResult:
    """Result from AI analysis"""
    model_used: str
    analysis_type: str
    issues_found: List[Dict[str, Any]]
    recommendations: List[str]
    confidence_score: float
    processing_time: float
    raw_response: str


@dataclass
class FileAnalysisResult:
    """Result for a specific file analysis"""
    file_path: str
    file_name: str
    total_lines: int
    issues: List[Dict[str, Any]]
    suggestions: List[str]
    old_patterns_found: List[Dict[str, Any]]
    improved_code: Optional[str] = None


@dataclass
class SonarQubeLLMResult:
    """SonarQube-style analysis using LLM"""
    quality_gate: str  # PASSED or FAILED
    bugs: int
    vulnerabilities: int
    code_smells: int
    coverage: float
    duplications: float
    issues: List[Dict[str, Any]]
    llm_insights: List[str]


class HuggingFaceAIService:
    """AI Service using Ford LLM API for code analysis (with HuggingFace fallback)."""
    
    def __init__(self):
        # Ford LLM (primary)
        self.ford_llm_enabled = FORD_LLM_ENABLED
        self.ford_llm_api_endpoint = FORD_LLM_API_ENDPOINT
        self.ford_llm_api_key = FORD_LLM_API_KEY
        self.ford_llm_model = FORD_LLM_MODEL
        self.ford_llm_proxy_url = FORD_LLM_PROXY_URL
        self.ford_llm_verify_ssl = FORD_LLM_VERIFY_SSL
        self.ford_llm_timeout = FORD_LLM_TIMEOUT
        self.ford_llm_extra_models = FORD_LLM_EXTRA_MODELS
        # HuggingFace (legacy fallback)
        self.api_key = HUGGINGFACE_API_KEY
        self.api_url = HUGGINGFACE_API_URL
        self.headers = (
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            if self.api_key
            else {}
        )
        self.available = bool(self.ford_llm_enabled and self.ford_llm_api_key) or bool(self.api_key)
        if self.ford_llm_enabled and self.ford_llm_api_key:
            logger.info("AI Service initialized with Ford LLM (model=%s)", self.ford_llm_model)
        else:
            logger.info(f"AI Service initialized with Hugging Face fallback (API Key: {'Configured' if self.api_key else 'Not Configured'})")
    
    async def query_huggingface(self, model_id: str, prompt: str, max_length: int = 1024) -> str:
        """Query LLM API — routes through Ford LLM first, falls back to HuggingFace."""
        # ── Primary: Ford LLM ──
        if self.ford_llm_enabled and self.ford_llm_api_key:
            try:
                return await self._query_ford_llm(prompt, max_length)
            except Exception as e:
                logger.warning("Ford LLM query failed, falling back to HuggingFace: %s", e)

        # ── Fallback: HuggingFace ──
        if not self.api_key:
            return "LLM API key not configured (neither Ford LLM nor Hugging Face)"
        
        url = f"{self.api_url}/{model_id}"
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_length,
                "temperature": 0.3,
                "top_p": 0.9,
                "return_full_text": False
            }
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.headers, json=payload, timeout=60) as response:
                    if response.status == 200:
                        result = await response.json()
                        if isinstance(result, list) and len(result) > 0:
                            return result[0].get("generated_text", "")
                        return str(result)
                    else:
                        error_text = await response.text()
                        logger.error(f"Hugging Face API error: {response.status} - {error_text}")
                        return f"API Error: {response.status}"
        except Exception as e:
            logger.error(f"Error querying Hugging Face: {e}")
            return f"Error: {str(e)}"

    async def _query_ford_llm(self, prompt: str, max_tokens: int = 1024) -> str:
        """Call Ford LLM chat/completions endpoint directly."""
        import httpx

        # Ensure fresh token via centralized token manager
        try:
            from services.token_manager import ford_token_manager
            if ford_token_manager.is_configured:
                fresh_token = ford_token_manager.ensure_fresh_token()
                if fresh_token:
                    self.ford_llm_api_key = fresh_token
        except Exception:
            pass

        headers = {
            "Authorization": f"Bearer {self.ford_llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.ford_llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": FORD_LLM_TEMPERATURE,
        }
        if self.ford_llm_extra_models:
            payload["extra_body"] = {"models": self.ford_llm_extra_models}

        proxy = self.ford_llm_proxy_url or None
        async with httpx.AsyncClient(
            timeout=float(self.ford_llm_timeout),
            **_proxy_kw(proxy),
            verify=self.ford_llm_verify_ssl,
        ) as client:
            response = await client.post(self.ford_llm_api_endpoint, headers=headers, json=payload)
            # Handle models that do not support custom temperature
            if response.status_code == 400 and "temperature" in (response.text or "").lower():
                payload.pop("temperature", None)
                logger.info("Model %s does not support custom temperature; retrying without it", self.ford_llm_model)
                response = await client.post(self.ford_llm_api_endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message", {})
                return (msg.get("content") or "").strip()
        return ""
    
    async def analyze_file_with_llm(
        self, 
        file_content: str, 
        file_path: str,
        source_version: str,
        target_version: str
    ) -> FileAnalysisResult:
        """Analyze a single Java file using LLM"""
        start_time = datetime.now()
        
        file_name = os.path.basename(file_path)
        total_lines = len(file_content.split('\n'))
        
        # Build prompt for code analysis
        prompt = f"""Analyze this Java {source_version} code for migration to Java {target_version}.

File: {file_name}

Code:
```java
{file_content[:3000]}  # Limit to first 3000 chars for API
```

Identify:
1. Deprecated APIs and old patterns that need updating
2. Business logic issues
3. Security vulnerabilities
4. Performance improvements

For each issue, provide:
- Line number (approximate)
- Issue type
- Severity (high/medium/low)
- Description
- Suggested fix

Format response as JSON with fields: issues, suggestions, old_patterns"""

        # Query LLM
        response = await self.query_huggingface(
            MODELS["code_analysis"], 
            prompt, 
            max_length=2000
        )
        
        # Parse response (with fallback)
        issues = []
        suggestions = []
        old_patterns = []
        
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                issues = parsed.get("issues", [])
                suggestions = parsed.get("suggestions", [])
                old_patterns = parsed.get("old_patterns", [])
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            # Fallback: create issue from raw response
            if response and "Error" not in response:
                issues.append({
                    "line_number": 1,
                    "type": "llm_analysis",
                    "severity": "medium",
                    "description": response[:200],
                    "suggested_fix": "Review code manually"
                })
        
        # Fallback pattern-based detection if LLM fails
        if not issues:
            issues = self._detect_common_issues(file_content, source_version, target_version)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return FileAnalysisResult(
            file_path=file_path,
            file_name=file_name,
            total_lines=total_lines,
            issues=issues,
            suggestions=suggestions or ["No specific suggestions from LLM"],
            old_patterns=old_patterns or self._detect_old_patterns(file_content),
            improved_code=None
        )
    
    def _detect_common_issues(self, code: str, source_version: str, target_version: str) -> List[Dict]:
        """Detect common Java migration issues"""
        issues = []
        lines = code.split('\n')
        
        for i, line in enumerate(lines, 1):
            # Check for deprecated APIs
            if 'new Date()' in line:
                issues.append({
                    "line_number": i,
                    "type": "deprecated_api",
                    "severity": "medium",
                    "description": "Consider using java.time.LocalDateTime instead of new Date()",
                    "code_snippet": line.strip()[:100],
                    "suggested_fix": "Replace with LocalDateTime.now()"
                })
            
            if 'SimpleDateFormat' in line:
                issues.append({
                    "line_number": i,
                    "type": "thread_safety",
                    "severity": "high",
                    "description": "SimpleDateFormat is not thread-safe. Use DateTimeFormatter instead.",
                    "code_snippet": line.strip()[:100],
                    "suggested_fix": "Use DateTimeFormatter.ofPattern(\"pattern\")"
                })
            
            if 'printStackTrace()' in line:
                issues.append({
                    "line_number": i,
                    "type": "logging",
                    "severity": "low",
                    "description": "printStackTrace() should be replaced with proper logging",
                    "code_snippet": line.strip()[:100],
                    "suggested_fix": "Use logger.error(\"message\", exception)"
                })
            
            if 'javax.annotation' in line and int(target_version) >= 11:
                issues.append({
                    "line_number": i,
                    "type": "package_migration",
                    "severity": "high",
                    "description": "javax.annotation package moved to jakarta.annotation in Java 11+",
                    "code_snippet": line.strip()[:100],
                    "suggested_fix": "Change import to jakarta.annotation.*"
                })
            
            if int(target_version) >= 17 and 'instanceof' in line and 'cast' in code:
                issues.append({
                    "line_number": i,
                    "type": "modern_java",
                    "severity": "low",
                    "description": "Consider using pattern matching for instanceof (Java 16+)",
                    "code_snippet": line.strip()[:100],
                    "suggested_fix": "Use if (obj instanceof String s) { ... }"
                })
        
        return issues
    
    def _detect_old_patterns(self, code: str) -> List[Dict]:
        """Detect old coding patterns"""
        patterns = []
        
        old_patterns_map = {
            'Vector': ('Use ArrayList instead of Vector', 'modern_collections'),
            'Hashtable': ('Use HashMap instead of Hashtable', 'modern_collections'),
            'StringBuffer': ('Use StringBuilder for better performance (unless thread-safe needed)', 'performance'),
            'Enumeration': ('Use Iterator instead of Enumeration', 'modern_collections'),
            'System.out.println': ('Use proper logging framework (SLF4J/Logback)', 'logging'),
            'e.printStackTrace()': ('Use logger.error() for proper error logging', 'logging'),
            'Runtime.exec': ('Use ProcessBuilder for better control', 'security'),
            'Thread.sleep': ('Consider using ScheduledExecutorService', 'concurrency'),
        }
        
        for pattern, (message, category) in old_patterns_map.items():
            if pattern in code:
                patterns.append({
                    "pattern": pattern,
                    "message": message,
                    "category": category,
                    "occurrences": code.count(pattern)
                })
        
        return patterns
    
    async def analyze_business_logic_llm(
        self,
        java_files: List[str],
        repo_url: str,
        source_version: str,
        target_version: str
    ) -> List[FileAnalysisResult]:
        """Analyze business logic across multiple files"""
        results = []
        
        for file_path in java_files[:10]:  # Limit to 10 files
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                result = await self.analyze_file_with_llm(
                    content, file_path, source_version, target_version
                )
                results.append(result)
                
            except Exception as e:
                logger.error(f"Error analyzing file {file_path}: {e}")
                results.append(FileAnalysisResult(
                    file_path=file_path,
                    file_name=os.path.basename(file_path),
                    total_lines=0,
                    issues=[],
                    suggestions=[f"Error analyzing file: {str(e)}"],
                    old_patterns=[]
                ))
        
        return results
    
    async def analyze_sonar_with_llm(self, project_path: str) -> SonarQubeLLMResult:
        """Perform SonarQube-style analysis using LLM"""
        start_time = datetime.now()
        
        all_issues = []
        llm_insights = []
        
        # Collect all Java files
        java_files = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['target', 'build', 'out', '.git', 'node_modules']]
            for file in files:
                if file.endswith('.java'):
                    java_files.append(os.path.join(root, file))
        
        # Analyze a sample of files
        sample_files = java_files[:5]
        
        for file_path in sample_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Build SonarQube-style prompt
                prompt = f"""Analyze this Java code for SonarQube-style quality checks:

Code:
```java
{content[:2000]}
```

Check for:
1. Bugs and reliability issues
2. Security vulnerabilities (OWASP Top 10)
3. Code smells and maintainability issues
4. Code duplication potential

Count and categorize issues by severity.
Provide a brief summary of findings."""

                response = await self.query_huggingface(
                    MODELS["code_quality"],
                    prompt,
                    max_length=1500
                )
                
                # Parse issues from response
                file_issues = self._parse_sonar_issues(response, file_path)
                all_issues.extend(file_issues)
                
                if response:
                    llm_insights.append(f"{os.path.basename(file_path)}: {response[:150]}")
                    
            except Exception as e:
                logger.error(f"Error in Sonar analysis for {file_path}: {e}")
        
        # Calculate metrics
        bugs = len([i for i in all_issues if i.get("category") == "bugs"])
        vulnerabilities = len([i for i in all_issues if i.get("category") == "security"])
        code_smells = len([i for i in all_issues if i.get("category") == "code_smell"])
        
        quality_gate = "PASSED" if bugs == 0 and vulnerabilities == 0 else "FAILED"
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return SonarQubeLLMResult(
            quality_gate=quality_gate,
            bugs=bugs,
            vulnerabilities=vulnerabilities,
            code_smells=code_smells,
            coverage=0.0,  # LLM can't measure coverage
            duplications=0.0,  # Would need more sophisticated analysis
            issues=all_issues[:20],  # Limit to top 20
            llm_insights=llm_insights
        )
    
    def _parse_sonar_issues(self, response: str, file_path: str) -> List[Dict]:
        """Parse SonarQube-style issues from LLM response"""
        issues = []
        
        # Simple pattern matching to extract issues
        # This is a basic implementation - could be improved with better parsing
        lines = response.split('\n')
        current_category = "general"
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Detect category headers
            if "bug" in line.lower():
                current_category = "bugs"
            elif "security" in line.lower() or "vulnerability" in line.lower():
                current_category = "security"
            elif "smell" in line.lower():
                current_category = "code_smell"
            
            # Detect issues (lines starting with numbers or dashes)
            if line.startswith('-') or line[0].isdigit():
                severity = "medium"
                if "critical" in line.lower() or "high" in line.lower():
                    severity = "high"
                elif "minor" in line.lower() or "low" in line.lower():
                    severity = "low"
                
                issues.append({
                    "file_path": file_path,
                    "category": current_category,
                    "severity": severity,
                    "message": line[:200],
                    "line_number": 0  # LLM doesn't always provide line numbers
                })
        
        return issues
    
    async def get_code_improvement_suggestion(
        self, 
        code_snippet: str, 
        issue_description: str
    ) -> str:
        """Get AI suggestion for improving specific code"""
        prompt = f"""Given this Java code with the following issue:

Issue: {issue_description}

Code:
```java
{code_snippet}
```

Provide the improved version of this code with the issue fixed.
Only return the improved code, no explanation."""

        response = await self.query_huggingface(
            MODELS["code_analysis"],
            prompt,
            max_length=1000
        )
        
        return response

    async def summarize_test_results(
        self,
        test_output: str,
        tests_run: int,
        tests_passed: int,
        tests_failed: int
    ) -> Dict[str, Any]:
        """Ask the LLM to summarize the latest automated test run"""
        snippet = (test_output or "").strip()[:1800]
        prompt = f"""You are a software QA expert. A Java project just executed {tests_run} tests (
{tests_passed} passed, {tests_failed} failed).

Logs:
{snippet}

Provide JSON with fields 'summary' (short sentence) and 'insights' (array of short observations or advice)."""

        response = await self.query_huggingface(
            MODELS["general"],
            prompt,
            max_length=900
        )

        summary = f"{tests_run} tests executed. {tests_passed} passed, {tests_failed} failed."
        insights: List[str] = []

        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                summary = parsed.get("summary", summary)
                parsed_insights = parsed.get("insights")
                if isinstance(parsed_insights, list):
                    insights = parsed_insights
                elif isinstance(parsed_insights, str):
                    insights = [parsed_insights]
        except Exception as e:
            logger.warning(f"Unable to parse test summary response: {e}")

        if not insights:
            if tests_failed > 0:
                insights.append("Investigate the failing tests; the log snippet above highlights the errors.")
            elif tests_run > 0:
                insights.append("LLM indicates the test suite completed without failures.")
            else:
                insights.append("No tests were executed. Run the suite to verify the migration.")

        return {
            "summary": summary,
            "insights": insights,
            "model_used": MODELS["general"]
        }


# Global instance
huggingface_ai_service = HuggingFaceAIService()
