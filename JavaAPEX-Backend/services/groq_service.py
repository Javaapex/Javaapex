"""
Groq LLM Service - Free, high-speed LLM API integration
Supports multiple open-source models via Groq's API

Features:
- Token tracking and usage monitoring
- Multiple model support
- Async-first architecture
- Enterprise error handling
- Cost optimization

Token Limits:
- Free tier: 30K tokens/month, 100 requests/day
- Paid tier: $0.20 per 30M tokens
- Per-request max: 4096 tokens (enforced)
"""
import os
import logging
import asyncio
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from groq import Groq

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Track token usage across requests"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    def __add__(self, other: 'TokenUsage') -> 'TokenUsage':
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens
        )


class GroqService:
    """Groq LLM client for code analysis and generation"""
    
    # Available models with capabilities
    AVAILABLE_MODELS = {
        "mixtral-8x7b-32768": {"desc": "Most capable, recommended", "context": 32768},
        "llama-3.1-70b-versatile": {"desc": "Large, versatile model", "context": 8000},
        "llama-3.1-8b-instant": {"desc": "Fast, compact model", "context": 8000},
        "gemma-7b-it": {"desc": "Efficient instruction-tuned", "context": 8000},
    }
    
    def __init__(self):
        """Initialize Groq service with API key from environment"""
        self.api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.model = os.getenv("GROQ_MODEL", "mixtral-8x7b-32768").strip()
        self.base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip()
        
        if not self.api_key:
            logger.warning(
                "GROQ_API_KEY not set. Get a free API key from https://console.groq.com"
            )
        
        self.client = Groq(api_key=self.api_key) if self.api_key else None
        self.cumulative_usage = TokenUsage()
        self._request_count = 0
        
        logger.info(f"Groq service initialized with model: {self.model}")

    async def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.9,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate text using Groq API with token tracking
        
        Args:
            prompt: User prompt
            max_tokens: Maximum tokens in response (capped at 4096)
            temperature: Sampling temperature (0.0-2.0)
            top_p: Nucleus sampling parameter
            system_prompt: Optional system prompt for context
            
        Returns:
            Dict with generated_text, model, tokens, and metadata
        """
        if not self.client:
            logger.error("Groq client not initialized. GROQ_API_KEY missing.")
            return {
                "success": False,
                "error": "Groq API key not configured",
                "generated_text": "",
                "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        
        try:
            messages = []
            
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            
            messages.append({
                "role": "user",
                "content": prompt
            })
            
            # Enforce max token limit
            enforced_max = min(max_tokens, 4096)
            
            # Run in executor to avoid blocking async
            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=enforced_max,
                    temperature=temperature,
                    top_p=top_p,
                ),
            )
            
            generated_text = completion.choices[0].message.content or ""
            
            # Track token usage
            usage = TokenUsage(
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens
            )
            self.cumulative_usage += usage
            self._request_count += 1
            
            logger.debug(f"Groq request #{self._request_count}: {usage.total_tokens} tokens")
            
            return {
                "success": True,
                "generated_text": generated_text,
                "model": self.model,
                "status_code": 200,
                "tokens": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                },
                "usage": {
                    "cumulative_tokens": self.cumulative_usage.total_tokens,
                    "cumulative_requests": self._request_count,
                }
            }
        
        except Exception as e:
            logger.error(f"Error calling Groq API: {e}")
            return {
                "success": False,
                "error": str(e),
                "generated_text": "",
                "model": self.model,
                "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

    async def code_analysis(
        self,
        code: str,
        analysis_type: str = "general",
    ) -> Dict[str, Any]:
        """
        Analyze code using Groq
        
        Args:
            code: Code snippet to analyze
            analysis_type: Type of analysis (general, security, performance, maintainability)
            
        Returns:
            Analysis results with issues and recommendations
        """
        analysis_prompts = {
            "general": """Analyze this Java code for issues, best practices, and improvements. 
Return a JSON response with structure:
{
    "issues": [{"type": "...", "severity": "high/medium/low", "description": "..."}],
    "recommendations": ["..."],
    "confidence_score": 0.9
}""",
            "security": """Analyze this Java code for security vulnerabilities and issues.
Return a JSON response with structure:
{
    "vulnerabilities": [{"type": "...", "severity": "high/medium/low", "description": "...", "fix": "..."}],
    "recommendations": ["..."],
    "confidence_score": 0.9
}""",
            "performance": """Analyze this Java code for performance issues and optimization opportunities.
Return a JSON response with structure:
{
    "issues": [{"type": "...", "description": "...", "optimization": "..."}],
    "recommendations": ["..."],
    "confidence_score": 0.9
}""",
            "maintainability": """Analyze this Java code for maintainability, readability, and design patterns.
Return a JSON response with structure:
{
    "issues": [{"type": "...", "description": "...", "suggestion": "..."}],
    "recommendations": ["..."],
    "confidence_score": 0.9
}""",
        }
        
        system_prompt = "You are an expert Java code analyst. Always respond with valid JSON."
        prompt = f"{analysis_prompts.get(analysis_type, analysis_prompts['general'])}\n\nCode to analyze:\n```java\n{code}\n```"
        
        return await self.generate_text(
            prompt=prompt,
            max_tokens=2048,
            system_prompt=system_prompt,
        )

    def check_availability(self) -> bool:
        """Check if Groq service is available and configured"""
        return self.client is not None and bool(self.api_key)

    def get_token_usage(self) -> Dict[str, Any]:
        """Get cumulative token usage statistics"""
        return {
            "prompt_tokens": self.cumulative_usage.prompt_tokens,
            "completion_tokens": self.cumulative_usage.completion_tokens,
            "total_tokens": self.cumulative_usage.total_tokens,
            "request_count": self._request_count,
            "avg_tokens_per_request": (
                self.cumulative_usage.total_tokens / self._request_count 
                if self._request_count > 0 else 0
            ),
        }

    def reset_usage_tracking(self) -> None:
        """Reset token usage tracking"""
        self.cumulative_usage = TokenUsage()
        self._request_count = 0
        logger.info("Token usage tracking reset")

    @classmethod
    def get_available_models(cls) -> Dict[str, Dict[str, Any]]:
        """Get list of available Groq models with capabilities"""
        return cls.AVAILABLE_MODELS

    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model"""
        return self.AVAILABLE_MODELS.get(model_name)


# Singleton instance
groq_service = GroqService()
