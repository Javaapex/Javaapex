"""
LLM Provider Configuration and Management
Centralized configuration for all LLM providers with intelligent fallback logic
"""
import os
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers"""
    GROQ = "groq"
    OPENAI = "openai"
    HUGGINGFACE = "huggingface"
    OLLAMA = "ollama"
    DEEPSEEK = "deepseek"
    FORDLLM = "fordllm"


class LLMProviderConfig:
    """
    Centralized LLM provider configuration
    Inspired by JavaAPEX-Backend enterprise patterns
    """
    
    # Provider priority (used for fallback chain)
    PROVIDER_PRIORITY = [
        LLMProvider.GROQ,
        LLMProvider.OPENAI,
        LLMProvider.HUGGINGFACE,
        LLMProvider.OLLAMA,
    ]
    
    # Provider configurations
    PROVIDER_CONFIGS = {
        LLMProvider.GROQ: {
            "api_key_env": "GROQ_API_KEY",
            "model_env": "GROQ_MODEL",
            "base_url_env": "GROQ_BASE_URL",
            "default_model": "mixtral-8x7b-32768",
            "max_tokens": 4096,
            "cost_per_1m_tokens": 0.20,  # Paid tier
            "free_tier": True,
            "free_tier_limit": "100 req/day, 30K tokens/month",
            "description": "Fast, free LLM API - RECOMMENDED",
        },
        LLMProvider.OPENAI: {
            "api_key_env": "OPENAI_API_KEY",
            "model_env": "OPENAI_MODEL",
            "base_url_env": "OPENAI_BASE_URL",
            "default_model": "gpt-3.5-turbo",
            "max_tokens": 4096,
            "cost_per_1m_tokens": 0.50,  # GPT-3.5
            "free_tier": False,
            "description": "High quality, commercial",
        },
        LLMProvider.HUGGINGFACE: {
            "api_key_env": "HUGGINGFACE_API_KEY",
            "model_env": "HUGGINGFACE_TEST_MODEL",
            "base_url_env": "HUGGINGFACE_ROUTER_BASE_URL",
            "default_model": "mistralai/Mistral-7B-Instruct-v0.3",
            "max_tokens": 2048,
            "cost_per_1m_tokens": 0,  # Free with rate limits
            "free_tier": True,
            "free_tier_limit": "Rate limited",
            "description": "Free tier with rate limits",
        },
        LLMProvider.OLLAMA: {
            "url_env": "OLLAMA_URL",
            "model_env": "OLLAMA_MODEL",
            "default_model": "deepseek-coder:6.7b-instruct",
            "max_tokens": 2048,
            "cost_per_1m_tokens": 0,  # Local
            "free_tier": True,
            "free_tier_limit": "Unlimited (local)",
            "description": "Completely free, runs locally",
        },
        LLMProvider.DEEPSEEK: {
            "api_key_env": "DEEPSEEK_API_KEY",
            "model_env": "DEEPSEEK_MODEL",
            "default_model": "deepseek-coder",
            "max_tokens": 4096,
            "cost_per_1m_tokens": 0.14,
            "free_tier": True,
            "free_tier_limit": "Limited free credits",
            "description": "Free credits available",
        },
    }
    
    @staticmethod
    def get_provider_config(provider: LLMProvider) -> Dict[str, str]:
        """Get configuration for a specific provider"""
        return LLMProviderConfig.PROVIDER_CONFIGS.get(provider, {})
    
    @staticmethod
    def get_configured_providers() -> List[LLMProvider]:
        """
        Get list of configured providers based on environment variables
        Returns providers in priority order
        """
        configured = []
        
        for provider in LLMProviderConfig.PROVIDER_PRIORITY:
            config = LLMProviderConfig.get_provider_config(provider)
            
            # Check if provider has necessary configuration
            if provider == LLMProvider.OLLAMA:
                url = os.getenv(config.get("url_env", ""), "").strip()
                if url:
                    configured.append(provider)
            elif provider == LLMProvider.OLLAMA:
                pass  # Handle Ollama specially if needed
            else:
                api_key = os.getenv(config.get("api_key_env", ""), "").strip()
                if api_key:
                    configured.append(provider)
        
        return configured
    
    @staticmethod
    def get_primary_provider() -> Optional[LLMProvider]:
        """Get the primary (first configured) provider"""
        env_provider = os.getenv("LLM_PROVIDER", "groq").lower()
        
        try:
            primary = LLMProvider(env_provider)
            config = LLMProviderConfig.get_provider_config(primary)
            
            if primary == LLMProvider.OLLAMA:
                url = os.getenv(config.get("url_env", ""), "").strip()
                if url:
                    return primary
            else:
                api_key = os.getenv(config.get("api_key_env", ""), "").strip()
                if api_key:
                    return primary
        except ValueError:
            pass
        
        # Fallback to first configured provider
        configured = LLMProviderConfig.get_configured_providers()
        return configured[0] if configured else None
    
    @staticmethod
    def get_fallback_chain() -> List[LLMProvider]:
        """
        Get fallback chain of providers
        Returns all configured providers in priority order
        """
        return LLMProviderConfig.get_configured_providers()
    
    @staticmethod
    def print_available_providers() -> None:
        """Print available providers and their configurations"""
        print("\n" + "="*80)
        print("Available LLM Providers")
        print("="*80 + "\n")
        
        for provider in LLMProvider:
            config = LLMProviderConfig.get_provider_config(provider)
            if not config:
                continue
            
            print(f"📦 {provider.value.upper()}")
            print(f"   Description: {config.get('description', 'N/A')}")
            print(f"   Default Model: {config.get('default_model', 'N/A')}")
            print(f"   Max Tokens: {config.get('max_tokens', 'N/A')}")
            print(f"   Cost: ${config.get('cost_per_1m_tokens', 'N/A')}/1M tokens")
            
            if config.get('free_tier'):
                print(f"   ✅ Free Tier: {config.get('free_tier_limit', 'Available')}")
            else:
                print(f"   ❌ No free tier (requires payment)")
            
            # Check if configured
            api_key_env = config.get('api_key_env') or config.get('url_env')
            if api_key_env:
                is_configured = bool(os.getenv(api_key_env, "").strip())
                status = "✅ CONFIGURED" if is_configured else "❌ NOT CONFIGURED"
                print(f"   Status: {status}")
            
            print()


class LLMTokenCounter:
    """
    Track and manage LLM token usage across all providers
    """
    
    def __init__(self):
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.request_count = 0
        self.provider_usage = {}
    
    def add_usage(
        self,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """Record token usage for a provider"""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.request_count += 1
        
        if provider not in self.provider_usage:
            self.provider_usage[provider] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        
        self.provider_usage[provider]["requests"] += 1
        self.provider_usage[provider]["prompt_tokens"] += prompt_tokens
        self.provider_usage[provider]["completion_tokens"] += completion_tokens
        self.provider_usage[provider]["total_tokens"] += total_tokens
        
        logger.debug(
            f"Token usage recorded for {provider}: "
            f"{prompt_tokens} prompt + {completion_tokens} completion = {total_tokens} total"
        )
    
    def get_usage_summary(self) -> Dict[str, any]:
        """Get summary of token usage"""
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "request_count": self.request_count,
            "avg_tokens_per_request": (
                self.total_tokens / self.request_count if self.request_count > 0 else 0
            ),
            "by_provider": self.provider_usage,
        }
    
    def estimate_cost(self, costs_per_1m_tokens: Dict[str, float]) -> Dict[str, float]:
        """Estimate cost of token usage"""
        costs = {}
        
        for provider, usage in self.provider_usage.items():
            cost_per_1m = costs_per_1m_tokens.get(provider, 0)
            if cost_per_1m > 0:
                cost = (usage["total_tokens"] / 1_000_000) * cost_per_1m
                costs[provider] = round(cost, 4)
            else:
                costs[provider] = 0
        
        return costs
    
    def reset(self) -> None:
        """Reset all counters"""
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.request_count = 0
        self.provider_usage = {}


# Global token counter instance
llm_token_counter = LLMTokenCounter()
