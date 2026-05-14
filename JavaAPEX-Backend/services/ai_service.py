"""
AI Service - Multi-Provider LLM Integration for Java Migration
Provides AI-powered code analysis using Groq, OpenAI, Hugging Face, or other providers

Architecture:
- Multi-level fallback chain
- Token tracking and usage monitoring
- Provider abstraction layer
- Enterprise error handling
- Async-first design
"""
import os
import json
import logging
import asyncio
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from datetime import datetime
import httpx
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


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
    tokens: Optional[Dict[str, int]] = None


@dataclass
class AIFixResult:
    """Result from AI fix generation"""
    model_used: str
    file_path: str
    original_code: str
    fixed_code: str
    fix_description: str
    confidence_score: float
    issues_resolved: List[str]
    tokens: Optional[Dict[str, int]] = None



class AIProviderFactory:
    """
    Factory for creating LLM provider instances with fallback chain support
    Implements enterprise-grade error handling and provider abstraction
    """
    
    # Cache provider instances to avoid repeated initialization
    _provider_cache = {}
    
    @classmethod
    def get_provider(cls, provider_name: str = "groq") -> Optional[Any]:
        """
        Get an LLM provider instance by name
        Returns None if provider not available
        """
        provider_name = (provider_name or "groq").lower()
        
        # Check cache first
        if provider_name in cls._provider_cache:
            return cls._provider_cache[provider_name]
        
        provider = None
        
        if provider_name == "groq":
            try:
                from services.groq_service import groq_service
                if groq_service.check_availability():
                    provider = groq_service
                    logger.debug("✓ Groq provider available")
            except Exception as e:
                logger.debug(f"Groq service not available: {e}")
        
        elif provider_name == "openai":
            try:
                from openai import OpenAI
                api_key = os.getenv("OPENAI_API_KEY", "").strip()
                if api_key:
                    provider = OpenAI(api_key=api_key)
                    logger.debug("✓ OpenAI provider available")
            except Exception as e:
                logger.debug(f"OpenAI provider not available: {e}")
        
        elif provider_name == "huggingface":
            try:
                from services.ai_service_huggingface import huggingface_ai_service
                if huggingface_ai_service:
                    provider = huggingface_ai_service
                    logger.debug("✓ HuggingFace provider available")
            except Exception as e:
                logger.debug(f"HuggingFace service not available: {e}")
        
        # Cache the result (even if None)
        cls._provider_cache[provider_name] = provider
        return provider
    
    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available providers"""
        available = []
        for provider_name in ["groq", "openai", "huggingface"]:
            if cls.get_provider(provider_name) is not None:
                available.append(provider_name)
        return available
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear provider cache (useful for testing)"""
        cls._provider_cache.clear()


class LLMAnalysisService:
    """
    Generic LLM analysis service supporting multiple providers with fallback
    
    Features:
    - Multi-level fallback chain
    - Token tracking
    - Enterprise error handling
    - Provider abstraction
    """
    
    def __init__(self, provider_name: str = "groq", enable_fallback: bool = True):
        """
        Initialize with specified provider
        
        Args:
            provider_name: Primary provider (groq, openai, huggingface)
            enable_fallback: Enable automatic fallback to other providers
        """
        self.primary_provider_name = (provider_name or "groq").lower()
        self.primary_provider = AIProviderFactory.get_provider(self.primary_provider_name)
        self.enable_fallback = enable_fallback
        self.current_provider_name = self.primary_provider_name
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        if not self.primary_provider and enable_fallback:
            logger.warning(
                f"Primary provider '{self.primary_provider_name}' not available, "
                "fallback enabled"
            )
        
        logger.info(
            f"LLM Analysis Service initialized with provider: {self.primary_provider_name}"
        )
    
    async def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate text using configured provider with fallback chain
        
        Fallback Chain:
        1. Try primary provider
        2. If failed and fallback enabled, try alternative providers
        3. If all fail, return graceful fallback response
        """
        # Try primary provider first
        if self.primary_provider:
            result = await self._call_provider(
                self.primary_provider,
                self.primary_provider_name,
                prompt,
                max_tokens,
                temperature,
                system_prompt
            )
            if result.get("success"):
                self.current_provider_name = self.primary_provider_name
                return result
        
        # If primary failed and fallback enabled, try alternatives
        if self.enable_fallback and not self.primary_provider:
            available = AIProviderFactory.get_available_providers()
            available = [p for p in available if p != self.primary_provider_name]
            
            for alt_provider_name in available:
                logger.debug(f"Trying fallback provider: {alt_provider_name}")
                alt_provider = AIProviderFactory.get_provider(alt_provider_name)
                
                if alt_provider:
                    result = await self._call_provider(
                        alt_provider,
                        alt_provider_name,
                        prompt,
                        max_tokens,
                        temperature,
                        system_prompt
                    )
                    if result.get("success"):
                        self.current_provider_name = alt_provider_name
                        logger.info(f"Successfully used fallback provider: {alt_provider_name}")
                        return result
        
        # All providers failed, return graceful fallback
        logger.warning("All LLM providers failed, returning fallback response")
        return self._fallback_response(prompt)
    
    async def _call_provider(
        self,
        provider: Any,
        provider_name: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
    ) -> Dict[str, Any]:
        """Internal method to call a specific provider with error handling"""
        try:
            if provider_name == "groq":
                return await provider.generate_text(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_prompt=system_prompt or "You are an expert Java code analyst."
                )
            elif provider_name == "openai":
                return await self._call_openai_provider(
                    provider, prompt, max_tokens, temperature, system_prompt
                )
            elif provider_name == "huggingface":
                return await provider.analyze_code(
                    prompt=prompt, analysis_type="general"
                )
        except Exception as e:
            logger.warning(f"Provider '{provider_name}' call failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _call_openai_provider(
        self, provider: Any, prompt: str, max_tokens: int, temperature: float,
        system_prompt: Optional[str]
    ) -> Dict[str, Any]:
        """Call OpenAI provider with async support"""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: provider.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
            
            tokens = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
            self.token_usage = {
                k: self.token_usage.get(k, 0) + v for k, v in tokens.items()
            }
            
            return {
                "success": True,
                "generated_text": completion.choices[0].message.content,
                "model": completion.model,
                "status_code": 200,
                "tokens": tokens,
            }
        except Exception as e:
            logger.error(f"OpenAI call failed: {e}")
            return {"success": False, "error": str(e)}
                "model": completion.model,
                "status_code": 200,
            }
        except Exception as e:
            logger.error(f"OpenAI call failed: {e}")
            return self._fallback_response(prompt)
    
    def _fallback_response(self, prompt: str) -> Dict[str, Any]:
        """Generate graceful fallback response when all providers unavailable"""
        logger.warning("All LLM providers unavailable, returning fallback response")
        
        fallback_text = """{
  "issues": [],
  "recommendations": [
    "LLM provider is not available or not configured",
    "Please configure environment variables for your chosen LLM provider",
    "Supported providers: groq (free), openai (paid), huggingface (free limited), ollama (local)"
  ],
  "confidence_score": 0.0
}"""
        
        return {
            "success": False,
            "generated_text": fallback_text,
            "model": "fallback",
            "status_code": 503,
            "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": "No LLM provider available",
        }
    
    def get_current_provider(self) -> str:
        """Get the currently active provider"""
        return self.current_provider_name
    
    def get_token_usage(self) -> Dict[str, int]:
        """Get cumulative token usage for this service"""
        return self.token_usage.copy()


class AIAnalysisService:
    """
    AI-powered analysis service for Java migration
    Supports multiple LLM providers with token tracking and error recovery
    """
    
    def __init__(self, provider: str = "groq", enable_fallback: bool = True):
        """
        Initialize with specified LLM provider
        
        Args:
            provider: Provider name (groq, openai, huggingface, ollama)
            enable_fallback: Enable fallback to alternative providers
        """
        self.provider_name = (provider or "groq").lower()
        self.llm_service = LLMAnalysisService(
            provider_name=self.provider_name,
            enable_fallback=enable_fallback
        )
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    
    def _update_token_usage(self, response: Dict[str, Any]) -> None:
        """Track token usage from response"""
        if isinstance(response, dict) and "tokens" in response:
            tokens = response.get("tokens", {})
            self.token_usage["prompt_tokens"] += tokens.get("prompt_tokens", 0)
            self.token_usage["completion_tokens"] += tokens.get("completion_tokens", 0)
            self.token_usage["total_tokens"] += tokens.get("total_tokens", 0)
    
    async def analyze_business_logic(self, code_content: str, file_path: str = "") -> AIAnalysisResult:
        """AI-powered business logic analysis with token tracking"""
        start_time = datetime.now()
        
        prompt = f"""
        Analyze this Java code for business logic issues and migration concerns:

        File: {file_path}
        Code:
        {code_content}

        Please identify and categorize the following issues:

        1. BUSINESS LOGIC ISSUES:
           - Incorrect business rule implementations
           - Logic errors that could cause incorrect behavior
           - Missing validation or edge case handling
           - Performance bottlenecks in business logic

        2. MIGRATION CONCERNS:
           - Java version compatibility issues
           - Deprecated API usage
           - Security vulnerabilities
           - Thread safety issues

        3. CODE QUALITY:
           - Maintainability concerns
           - Code smells
           - Best practice violations

        Return your analysis in JSON format with this structure:
        {{
          "issues": [
            {{
              "type": "business_logic|migration|code_quality",
              "severity": "high|medium|low",
              "category": "specific category",
              "description": "detailed description",
              "line_number": optional_line_number,
              "code_snippet": "relevant code snippet"
            }}
          ],
          "recommendations": ["list of recommendations"],
          "confidence_score": 0.0-1.0
        }}

        Focus on actionable issues that need attention during Java migration.
        """
        
        result = await self.llm_service.generate_text(
            prompt=prompt,
            max_tokens=1500,
            temperature=0.3,
            system_prompt="You are an expert Java code analyst. Always respond with valid JSON."
        )
        
        # Track token usage
        self._update_token_usage(result)
        processing_time = (datetime.now() - start_time).total_seconds()
        
        if result.get("success", False):
            try:
                # Parse JSON response
                analysis_data = json.loads(result.get("generated_text", "{}"))
                
                return AIAnalysisResult(
                    model_used=result.get("model", self.provider_name),
                    analysis_type="business_logic",
                    issues_found=analysis_data.get("issues", []),
                    recommendations=analysis_data.get("recommendations", []),
                    confidence_score=analysis_data.get("confidence_score", 0.8),
                    processing_time=processing_time,
                    raw_response=result.get("generated_text", ""),
                    tokens=result.get("tokens", {})
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse JSON response: {e}")
                return AIAnalysisResult(
                    model_used=result.get("model", self.provider_name),
                    analysis_type="business_logic",
                    issues_found=[],
                    recommendations=["Unable to parse detailed analysis"],
                    confidence_score=0.0,
                    processing_time=processing_time,
                    raw_response=result.get("generated_text", ""),
                    tokens=result.get("tokens", {})
                )
        else:
            return AIAnalysisResult(
                model_used=result.get("model", self.provider_name),
                analysis_type="business_logic",
                issues_found=[],
                recommendations=[f"Analysis failed: {result.get('error', 'Unknown error')}"],
                confidence_score=0.0,
                processing_time=processing_time,
                raw_response="",
                tokens=result.get("tokens", {})
            )
    
    async def analyze_code_quality(self, project_path: str) -> AIAnalysisResult:
        """AI-powered code quality analysis (replaces SonarQube)"""
        start_time = datetime.now()
        
        # Scan all Java files in the project
        java_files = []
        for root, dirs, files in os.walk(project_path):
            # Skip build directories
            dirs[:] = [d for d in dirs if d not in ['target', 'build', 'out', '.git']]
            
            for file in files:
                if file.endswith('.java'):
                    java_files.append(os.path.join(root, file))
        
        if not java_files:
            return AIAnalysisResult(
                model_used="",
                analysis_type="code_quality",
                issues_found=[],
                recommendations=["No Java files found"],
                confidence_score=0.0,
                processing_time=0.0,
                raw_response=""
            )
        
        # Analyze a sample of files (limit to avoid API limits)
        sample_files = java_files[:10]  # Analyze first 10 files
        all_issues = []
        all_recommendations = []
        
        for file_path in sample_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    code_content = f.read()
                
                prompt = f"""
                Perform a comprehensive code quality analysis on this Java file:

                File: {file_path}
                Code:
                {code_content[:5000]}  <!-- Limit to first 5000 chars -->

                Analyze for:
                1. Code smells and anti-patterns
                2. Maintainability issues
                3. Performance concerns
                4. Security vulnerabilities
                5. Best practice violations
                6. Complexity issues

                Return JSON with issues found.
                """
                
                model = self.models["code_quality"]
                if not self.available_models["code_quality"]:
                    model = self.models["general_analysis"]
                
                result = await self.hf_api.generate_text(model, prompt, max_tokens=1000, temperature=0.3)
                
                if result["success"]:
                    try:
                        analysis_data = json.loads(result["generated_text"])
                        all_issues.extend(analysis_data.get("issues", []))
                        all_recommendations.extend(analysis_data.get("recommendations", []))
                    except:
                        pass
                        
            except Exception as e:
                logger.error(f"Error analyzing file {file_path}: {e}")
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return AIAnalysisResult(
            model_used=model,
            analysis_type="code_quality",
            issues_found=all_issues,
            recommendations=all_recommendations,
            confidence_score=0.8,
            processing_time=processing_time,
            raw_response=f"Analyzed {len(sample_files)} files"
        )
    
    async def analyze_dependencies(self, project_path: str) -> AIAnalysisResult:
        """AI-powered dependency analysis and recommendations"""
        start_time = datetime.now()
        
        # Find and read build files
        build_files = []
        for filename in ['pom.xml', 'build.gradle', 'build.gradle.kts']:
            filepath = os.path.join(project_path, filename)
            if os.path.exists(filepath):
                build_files.append(filepath)
        
        if not build_files:
            return AIAnalysisResult(
                model_used="",
                analysis_type="dependencies",
                issues_found=[],
                recommendations=["No build files found"],
                confidence_score=0.0,
                processing_time=0.0,
                raw_response=""
            )
        
        build_content = ""
        for filepath in build_files:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    build_content += f"\n\n=== {filepath} ===\n{f.read()}"
            except Exception as e:
                logger.error(f"Error reading {filepath}: {e}")
        
        prompt = f"""
        Analyze this Java project's dependencies for migration readiness:

        Build Configuration:
        {build_content}

        Please analyze and provide:
        1. Dependency compatibility with newer Java versions
        2. Outdated dependencies that need updates
        3. Dependencies that may cause migration issues
        4. Security vulnerabilities in dependencies
        5. Recommended dependency versions for Java migration

        Return JSON with dependency analysis and recommendations.
        """
        
        model = self.models["dependency_analysis"]
        if not self.available_models["dependency_analysis"]:
            model = self.models["general_analysis"]
        
        result = await self.hf_api.generate_text(model, prompt, max_tokens=1200, temperature=0.3)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        if result["success"]:
            try:
                analysis_data = json.loads(result["generated_text"])
                
                return AIAnalysisResult(
                    model_used=model,
                    analysis_type="dependencies",
                    issues_found=analysis_data.get("issues", []),
                    recommendations=analysis_data.get("recommendations", []),
                    confidence_score=analysis_data.get("confidence_score", 0.8),
                    processing_time=processing_time,
                    raw_response=result["generated_text"]
                )
            except:
                return AIAnalysisResult(
                    model_used=model,
                    analysis_type="dependencies",
                    issues_found=[],
                    recommendations=["Unable to parse dependency analysis"],
                    confidence_score=0.0,
                    processing_time=processing_time,
                    raw_response=result["generated_text"]
                )
        else:
            return AIAnalysisResult(
                model_used=model,
                analysis_type="dependencies",
                issues_found=[],
                recommendations=[f"Dependency analysis failed: {result.get('error', 'Unknown error')}"],
                confidence_score=0.0,
                processing_time=processing_time,
                raw_response=""
            )
    
    async def generate_automated_fixes(
        self, 
        issues: List[Dict[str, Any]], 
        code_content: str, 
        file_path: str = ""
    ) -> List[AIFixResult]:
        """AI-powered automated code fixes"""
        fixes = []
        
        # Group issues by type for batch processing
        business_logic_issues = [issue for issue in issues if issue.get("type") == "business_logic"]
        code_quality_issues = [issue for issue in issues if issue.get("type") == "code_quality"]
        migration_issues = [issue for issue in issues if issue.get("type") == "migration"]
        
        # Generate fixes for each category
        if business_logic_issues:
            fix_result = await self._generate_fixes_for_issues(
                business_logic_issues, code_content, file_path, "business_logic"
            )
            fixes.extend(fix_result)
        
        if code_quality_issues:
            fix_result = await self._generate_fixes_for_issues(
                code_quality_issues, code_content, file_path, "code_quality"
            )
            fixes.extend(fix_result)
        
        if migration_issues:
            fix_result = await self._generate_fixes_for_issues(
                migration_issues, code_content, file_path, "migration"
            )
            fixes.extend(fix_result)
        
        return fixes
    
    async def _generate_fixes_for_issues(
        self, 
        issues: List[Dict[str, Any]], 
        code_content: str, 
        file_path: str, 
        issue_type: str
    ) -> List[AIFixResult]:
        """Generate fixes for a specific type of issues"""
        fixes = []
        
        prompt = f"""
        Generate specific code fixes for these {issue_type} issues:

        File: {file_path}
        Issues:
        {json.dumps(issues, indent=2)}

        Current Code:
        {code_content[:3000]}  <!-- Limit code length -->

        Please provide specific code fixes for each issue. For each fix, return:
        1. The exact code changes needed
        2. Before and after code snippets
        3. Explanation of why this fix resolves the issue
        4. Any potential side effects

        Return your response in JSON format with this structure:
        {{
          "fixes": [
            {{
              "issue_id": "issue identifier",
              "fix_description": "description of the fix",
              "original_code": "the problematic code snippet",
              "fixed_code": "the corrected code snippet",
              "confidence_score": 0.0-1.0,
              "side_effects": "potential side effects"
            }}
          ]
        }}
        """
        
        model = self.models["automated_fixes"]
        if not self.available_models["automated_fixes"]:
            model = self.models["general_analysis"]
        
        result = await self.hf_api.generate_text(model, prompt, max_tokens=2000, temperature=0.2)
        
        if result["success"]:
            try:
                fix_data = json.loads(result["generated_text"])
                
                for fix in fix_data.get("fixes", []):
                    fixes.append(AIFixResult(
                        model_used=model,
                        file_path=file_path,
                        original_code=fix.get("original_code", ""),
                        fixed_code=fix.get("fixed_code", ""),
                        fix_description=fix.get("fix_description", ""),
                        confidence_score=fix.get("confidence_score", 0.8),
                        issues_resolved=[fix.get("issue_id", "")]
                    ))
            except:
                logger.warning("Failed to parse fix generation response")
        
        return fixes
    
    async def detect_project_metadata_with_llm(
        self, 
        all_files: List[Dict[str, Any]], 
        repository: Any = None,
        project_path: str = None
    ) -> Dict[str, Any]:
        """
        Use Hugging Face LLM to detect Java version, build tool, and framework
        by analyzing ALL files with their content in the repository
        """
        logger.info("Starting LLM-based project metadata detection with file contents")
        
        start_time = datetime.now()
        
        # Collect ALL files with their content for analysis
        build_files = []
        config_files = []
        java_files_sample = []
        all_file_contents = []  # Store all file contents for comprehensive analysis
        
        logger.info(f"Processing {len(all_files)} files for LLM analysis")
        
        # Process files - they should already have content from github_service
        for file_info in all_files:
            try:
                file_path = file_info.get("path", "")
                file_name = file_info.get("name", "")
                content = file_info.get("content")  # Content should already be fetched
                
                if not content:
                    continue  # Skip files without content
                
                # Collect all file info
                file_data = {
                    "path": file_path,
                    "name": file_name,
                    "content": content[:10000] if len(content) > 10000 else content  # Limit to 10KB per file
                }
                all_file_contents.append(file_data)
                
                # Prioritize build files
                if file_name in ["pom.xml", "build.gradle", "build.gradle.kts"]:
                    build_files.append(file_data)
                
                # Config files
                elif file_name in ["application.properties", "application.yml", "application.yaml", 
                                  "web.xml", "module-info.java", "package.json"]:
                    config_files.append(file_data)
                
                # Sample Java files (collect more for better analysis)
                elif file_name.endswith(".java") and len(java_files_sample) < 20:
                    java_files_sample.append(file_data)
                    
            except Exception as e:
                logger.warning(f"Could not process file {file_info.get('path', '')}: {e}")
                continue
        
        logger.info(f"Collected: {len(build_files)} build files, {len(config_files)} config files, {len(java_files_sample)} Java files")
        
        # Prepare prompt for LLM
        prompt = self._create_metadata_detection_prompt(build_files, config_files, java_files_sample)
        
        # Call Hugging Face LLM
        model = self.models["general_analysis"]
        result = await self.hf_api.generate_text(
            model, 
            prompt, 
            max_tokens=2000, 
            temperature=0.2  # Lower temperature for more deterministic results
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Parse LLM response
        metadata = self._parse_metadata_response(result, processing_time)
        
        return metadata
    
    def _create_metadata_detection_prompt(
        self, 
        build_files: List[Dict], 
        config_files: List[Dict], 
        java_files: List[Dict]
    ) -> str:
        """Create prompt for LLM to detect project metadata"""
        
        prompt = """Analyze the following repository files and detect:
1. Java version (e.g., 8, 11, 17, 21)
2. Build tool (e.g., Maven, Gradle, Ant)
3. Framework (e.g., Spring Boot, Spring, Hibernate, Jakarta EE, Micronaut, Quarkus)

"""
        
        # Add build files
        if build_files:
            prompt += "=== BUILD FILES ===\n\n"
            for bf in build_files:
                prompt += f"--- {bf['path']} ---\n"
                prompt += f"{bf['content']}\n\n"
        
        # Add config files
        if config_files:
            prompt += "=== CONFIGURATION FILES ===\n\n"
            for cf in config_files:
                prompt += f"--- {cf['path']} ---\n"
                prompt += f"{cf['content']}\n\n"
        
        # Add Java files sample
        if java_files:
            prompt += "=== JAVA SOURCE FILES (Sample) ===\n\n"
            for jf in java_files[:5]:  # Limit to 5 for prompt size
                prompt += f"--- {jf['path']} ---\n"
                prompt += f"{jf['content']}\n\n"
        
        prompt += """Based on the files above, provide your analysis in this exact JSON format:
{
  "java_version": {
    "version": "detected version number (e.g., 17)",
    "confidence": 0.0-1.0,
    "detected_from": "which file/element detected this"
  },
  "build_tool": {
    "tool": "Maven|Gradle|Ant|Other",
    "confidence": 0.0-1.0,
    "detected_from": "which file detected this"
  },
  "framework": {
    "primary_framework": "Spring Boot|Spring|Hibernate|Jakarta EE|Micronaut|Quarkus|Other",
    "additional_frameworks": ["list any other frameworks detected"],
    "confidence": 0.0-1.0,
    "detected_from": "which files/imports detected this"
  },
  "analysis_summary": "brief explanation of how you determined these values",
  "migration_recommendations": [
    "specific recommendation 1",
    "specific recommendation 2"
  ]
}

Important: Return ONLY the JSON, no other text."""
        
        return prompt
    
    def _parse_metadata_response(self, result: Dict[str, Any], processing_time: float) -> Dict[str, Any]:
        """Parse LLM response to extract metadata"""
        
        default_response = {
            "java_version": {"version": "unknown", "confidence": 0.0, "detected_from": "fallback"},
            "build_tool": {"tool": "unknown", "confidence": 0.0, "detected_from": "fallback"},
            "framework": {"primary_framework": "unknown", "additional_frameworks": [], "confidence": 0.0, "detected_from": "fallback"},
            "analysis_summary": "Could not detect metadata",
            "migration_recommendations": [],
            "processing_time": processing_time,
            "source": "llm_fallback"
        }
        
        if not result.get("success"):
            logger.error(f"LLM call failed: {result.get('error')}")
            return default_response
        
        try:
            # Extract JSON from response
            generated_text = result.get("generated_text", "")
            
            # Find JSON block
            json_start = generated_text.find("{")
            json_end = generated_text.rfind("}")
            
            if json_start == -1 or json_end == -1:
                logger.warning("No JSON found in LLM response")
                return default_response
            
            json_str = generated_text[json_start:json_end + 1]
            metadata = json.loads(json_str)
            
            # Add processing info
            metadata["processing_time"] = processing_time
            metadata["source"] = "fordllm"
            metadata["model_used"] = result.get("model", "unknown")
            
            return metadata
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            return default_response
        except Exception as e:
            logger.error(f"Error parsing metadata response: {e}")
            return default_response

    async def comprehensive_analysis(self, project_path: str) -> Dict[str, AIAnalysisResult]:
        """Run comprehensive AI analysis on the entire project"""
        logger.info(f"Starting comprehensive AI analysis for {project_path}")
        
        results = {}
        
        # Run all analyses in parallel
        tasks = {
            "business_logic": self.analyze_business_logic("", ""),  # Will be filled per file
            "code_quality": self.analyze_code_quality(project_path),
            "dependencies": self.analyze_dependencies(project_path)
        }
        
        # For business logic, analyze key files individually
        key_files = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['target', 'build', 'out', '.git']]
            for file in files:
                if file.endswith('.java') and ('Service' in file or 'Controller' in file or 'Manager' in file):
                    key_files.append(os.path.join(root, file))
        
        # Analyze key business logic files
        business_logic_results = []
        for file_path in key_files[:5]:  # Limit to 5 key files
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    code_content = f.read()
                
                result = await self.analyze_business_logic(code_content, file_path)
                business_logic_results.append(result)
            except Exception as e:
                logger.error(f"Error analyzing business logic file {file_path}: {e}")
        
        # Combine business logic results
        combined_issues = []
        combined_recommendations = []
        for result in business_logic_results:
            combined_issues.extend(result.issues_found)
            combined_recommendations.extend(result.recommendations)
        
        results["business_logic"] = AIAnalysisResult(
            model_used=business_logic_results[0].model_used if business_logic_results else "",
            analysis_type="business_logic",
            issues_found=combined_issues,
            recommendations=combined_recommendations,
            confidence_score=sum(r.confidence_score for r in business_logic_results) / len(business_logic_results) if business_logic_results else 0.0,
            processing_time=sum(r.processing_time for r in business_logic_results),
            raw_response=f"Analyzed {len(business_logic_results)} business logic files"
        )
        
        # Run other analyses
        code_quality_task = asyncio.create_task(self.analyze_code_quality(project_path))
        dependencies_task = asyncio.create_task(self.analyze_dependencies(project_path))
        
        results["code_quality"] = await code_quality_task
        results["dependencies"] = await dependencies_task
        
        logger.info("Comprehensive AI analysis completed")
        return results


class AIMigrationService:
    """AI-powered migration service that replaces manual migration"""
    
    def __init__(self):
        self.ai_service = AIAnalysisService()
    
    async def ai_driven_migration(self, project_path: str, target_java_version: str) -> Dict[str, Any]:
        """Complete AI-driven migration process"""
        logger.info(f"Starting AI-driven migration to Java {target_java_version}")
        
        # Step 1: Comprehensive AI Analysis
        analysis_results = await self.ai_service.comprehensive_analysis(project_path)
        
        # Step 2: Generate AI fixes for all issues
        all_issues = []
        for analysis_type, result in analysis_results.items():
            all_issues.extend(result.issues_found)
        
        # Apply fixes to files
        fixes_applied = 0
        files_modified = 0
        
        # Find all Java files to apply fixes
        java_files = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['target', 'build', 'out', '.git']]
            for file in files:
                if file.endswith('.java'):
                    java_files.append(os.path.join(root, file))
        
        for file_path in java_files[:20]:  # Limit to 20 files for performance
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    original_content = f.read()
                
                # Generate fixes for this file
                file_issues = [issue for issue in all_issues if issue.get("file_path") == file_path]
                if not file_issues:
                    continue
                
                fixes = await self.ai_service.generate_automated_fixes(file_issues, original_content, file_path)
                
                # Apply fixes (simplified - in practice you'd need more sophisticated code replacement)
                modified_content = original_content
                for fix in fixes:
                    if fix.original_code and fix.fixed_code:
                        modified_content = modified_content.replace(fix.original_code, fix.fixed_code)
                        fixes_applied += 1
                
                # Write back if modified
                if modified_content != original_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(modified_content)
                    files_modified += 1
                    
            except Exception as e:
                logger.error(f"Error applying fixes to {file_path}: {e}")
        
        # Step 3: Update build files for Java version
        await self._update_build_files(project_path, target_java_version)
        
        # Step 4: Generate migration report
        total_issues = len(all_issues)
        resolved_issues = fixes_applied
        
        return {
            "migration_type": "ai_driven",
            "target_java_version": target_java_version,
            "analysis_results": {
                analysis_type: {
                    "issues_found": len(result.issues_found),
                    "recommendations": len(result.recommendations),
                    "confidence_score": result.confidence_score,
                    "processing_time": result.processing_time
                }
                for analysis_type, result in analysis_results.items()
            },
            "migration_summary": {
                "total_issues_found": total_issues,
                "issues_resolved": resolved_issues,
                "files_modified": files_modified,
                "fixes_applied": fixes_applied,
                "success_rate": (resolved_issues / total_issues * 100) if total_issues > 0 else 0
            },
            "ai_models_used": list(set(result.model_used for result in analysis_results.values())),
            "timestamp": datetime.now().isoformat()
        }
    
    async def _update_build_files(self, project_path: str, target_version: str):
        """Update build files for target Java version"""
        # Update pom.xml
        pom_path = os.path.join(project_path, "pom.xml")
        if os.path.exists(pom_path):
            try:
                with open(pom_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Update Java version properties
                import re
                content = re.sub(r'<java\.version>[^<]+</java\.version>', f'<java.version>{target_version}</java.version>', content)
                content = re.sub(r'<maven\.compiler\.source>[^<]+</maven\.compiler\.source>', f'<maven.compiler.source>{target_version}</maven.compiler.source>', content)
                content = re.sub(r'<maven\.compiler\.target>[^<]+</maven\.compiler\.target>', f'<maven.compiler.target>{target_version}</maven.compiler.target>', content)
                
                with open(pom_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            except Exception as e:
                logger.error(f"Error updating pom.xml: {e}")
        
        # Update build.gradle
        gradle_path = os.path.join(project_path, "build.gradle")
        if os.path.exists(gradle_path):
            try:
                with open(gradle_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                import re
                content = re.sub(r'sourceCompatibility\s*=\s*["\']?\d+["\']?', f'sourceCompatibility = "{target_version}"', content)
                content = re.sub(r'targetCompatibility\s*=\s*["\']?\d+["\']?', f'targetCompatibility = "{target_version}"', content)
                
                with open(gradle_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            except Exception as e:
                logger.error(f"Error updating build.gradle: {e}")


# Global instances
ai_analysis_service = AIAnalysisService()
ai_migration_service = AIMigrationService()
