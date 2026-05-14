# LLM Provider Configuration Guide

## Overview

The JavaAPEX Backend now supports multiple LLM providers for Java code analysis and migration. The default is **Groq**, which is free and fast.

## Quick Setup

### 1. Groq (Recommended - Free)

```bash
# Get API key from https://console.groq.com
# Add to .env:
GROQ_API_KEY=gsk_your_api_key_here
```

That's it! The application will use Groq by default.

### 2. Using Different Providers

```python
from services.ai_service import AIAnalysisService

# Use Groq (default, free)
ai = AIAnalysisService(provider="groq")

# Use OpenAI (paid, high quality)
ai = AIAnalysisService(provider="openai")

# Use HuggingFace (free with limits)
ai = AIAnalysisService(provider="huggingface")

# Use Ollama (local, completely free)
ai = AIAnalysisService(provider="ollama")

# Analyze code
result = await ai.analyze_business_logic(code, "file.java")
```

## Provider Details

### Groq (⭐ Recommended)
- **Cost**: Free ($0/month for 100 requests/day, 30K/month)
- **Setup Time**: 2 minutes
- **Quality**: Excellent
- **Speed**: ⚡ Enterprise-grade (very fast)
- **Models**: Mixtral 8x7B, Llama 3.1, Gemma
- **Sign up**: https://console.groq.com

### HuggingFace (Free with Rate Limits)
- **Cost**: Free tier available
- **Setup Time**: 5 minutes
- **Quality**: Good
- **Speed**: Medium
- **Models**: Mistral, Zephyr, T5, etc.
- **Sign up**: https://huggingface.co/settings/tokens

### Ollama (Completely Free - Local)
- **Cost**: Free (runs on your machine)
- **Setup Time**: 5 minutes (install + download model)
- **Quality**: Good
- **Speed**: Slow (depends on your hardware)
- **Models**: Local - Deepseek Coder, Llama, Mistral
- **Install**: https://ollama.ai

### OpenAI (High Quality - Paid)
- **Cost**: $0.50-$1.50/1M tokens (GPT-3.5), $30-$60/1M (GPT-4)
- **Setup Time**: 2 minutes
- **Quality**: Best-in-class
- **Speed**: Fast
- **Models**: GPT-3.5-turbo, GPT-4
- **Sign up**: https://platform.openai.com

### DeepSeek (Free with Limited Credits)
- **Cost**: Free credits + paid tier
- **Setup Time**: 5 minutes
- **Quality**: Good
- **Speed**: Fast
- **Models**: DeepSeek Coder, DeepSeek Chat
- **Sign up**: https://www.deepseek.com/api

## Environment Variables

### Groq
```bash
GROQ_API_KEY=gsk_...
GROQ_MODEL=mixtral-8x7b-32768
GROQ_BASE_URL=https://api.groq.com/openai/v1
```

### OpenAI
```bash
OPENAI_API_KEY=sk_...
OPENAI_MODEL=gpt-3.5-turbo
```

### HuggingFace
```bash
HUGGINGFACE_API_KEY=hf_...
HUGGINGFACE_TEST_MODELS=mistralai/Mistral-7B-Instruct-v0.3
```

### DeepSeek
```bash
DEEPSEEK_API_KEY=...
DEESEEK_API_KEY=...  # Note: typo kept for compatibility
```

### Ollama
```bash
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=deepseek-coder:6.7b-instruct
```

### Global
```bash
# Test provider (groq, openai, huggingface, ollama, deepseek)
LLM_TEST_PROVIDER=groq
```

## Service Files

### Core Services

1. **`services/groq_service.py`**
   - Groq-specific implementation
   - Fast, free LLM provider
   - Supports multiple models
   - Code analysis capabilities

2. **`services/ai_service.py`**
   - Multi-provider abstraction layer
   - `AIProviderFactory` - Creates provider instances
   - `LLMAnalysisService` - Generic analysis service
   - `AIAnalysisService` - Business logic analysis

3. **`services/llm_test_pipeline.py`**
   - LLM-based test generation
   - Supports all providers
   - Test execution and reporting

## Usage Examples

### Example 1: Basic Code Analysis with Groq

```python
from services.groq_service import groq_service

code = """
public class Example {
    public void process(List<Item> items) {
        for (Item item : items) {
            if (item.isValid()) {
                processItem(item);
            }
        }
    }
}
"""

result = await groq_service.code_analysis(code, "general")
print(result)
```

### Example 2: Using LLMAnalysisService with Multiple Providers

```python
from services.ai_service import LLMAnalysisService

# Switch between providers
for provider in ["groq", "huggingface", "ollama"]:
    service = LLMAnalysisService(provider_name=provider)
    result = await service.generate_text(
        prompt="Analyze this Java code...",
        max_tokens=2048
    )
    print(f"{provider}: {result}")
```

### Example 3: Business Logic Analysis

```python
from services.ai_service import AIAnalysisService

# Create service with Groq (default)
ai_service = AIAnalysisService(provider="groq")

# Analyze code
result = await ai_service.analyze_business_logic(
    code_content="""
        public int calculateDiscount(double price) {
            if (price > 100) {
                return 20;
            } else if (price > 50) {
                return 10;
            }
            return 0;
        }
    """,
    file_path="DiscountService.java"
)

print(f"Issues found: {len(result.issues_found)}")
print(f"Recommendations: {result.recommendations}")
print(f"Model used: {result.model_used}")
```

### Example 4: API Endpoint Usage

```bash
# Run migrations with specific LLM provider
POST /api/migration/analyze?llm_test_provider=groq

# Re-run tests with different provider
POST /api/migration/{job_id}/rerun-tests?llm_provider=groq
```

## Recommended Configuration

### For Development (Free)
```bash
# Copy this to your .env file
GROQ_API_KEY=gsk_your_free_key_here
GROQ_MODEL=mixtral-8x7b-32768
LLM_TEST_PROVIDER=groq
```

### For Production (High Quality)
```bash
# Use OpenAI or Groq paid tier
GROQ_API_KEY=gsk_prod_key_here  # Paid tier
# OR
OPENAI_API_KEY=sk_prod_key_here
LLM_TEST_PROVIDER=groq  # or openai
```

### For Privacy (Local Only)
```bash
# Use Ollama - completely private
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=deepseek-coder:6.7b-instruct
LLM_TEST_PROVIDER=ollama
```

## Troubleshooting

### Issue: "Provider not available"
```python
# Check which providers are configured
from services.ai_service import AIProviderFactory
provider = AIProviderFactory.get_provider("groq")
if provider is None:
    print("Configure GROQ_API_KEY in .env")
```

### Issue: "Rate limit exceeded"
- Groq free tier: max 100 requests/day
- Use Ollama for testing (no limits, local)
- Upgrade to paid tier for production

### Issue: "API key validation failed"
- Verify key format (Groq: `gsk_...`, OpenAI: `sk_...`)
- Check key is active in provider console
- Ensure no extra spaces in .env file

## Advanced Configuration

### Use Different Models Based on Task

```python
# Fast analysis - small model
os.environ["GROQ_MODEL"] = "llama-3.1-8b-instant"

# Detailed analysis - large model
os.environ["GROQ_MODEL"] = "mixtral-8x7b-32768"

# Load from environment
from services.groq_service import groq_service
# Now using the configured model
```

### Fallback Chain

```python
# Automatically fallback if primary provider fails
providers = ["groq", "openai", "huggingface", "ollama"]
for provider in providers:
    service = AIAnalysisService(provider=provider)
    try:
        result = await service.analyze_business_logic(code)
        print(f"Analysis complete using {provider}")
        break
    except Exception as e:
        print(f"Failed with {provider}, trying next...")
```

## Cost Analysis

For analyzing 1000 files (~100 pages each):

| Provider | Cost | Time | Quality |
|----------|------|------|---------|
| Groq (free) | $0 | 5 mins | ⭐⭐⭐⭐ |
| Groq (paid) | ~$0.20 | 5 mins | ⭐⭐⭐⭐ |
| OpenAI | ~$5-10 | 10 mins | ⭐⭐⭐⭐⭐ |
| HuggingFace | Free | 30 mins | ⭐⭐⭐ |
| Ollama | Free | 2 hours | ⭐⭐⭐ |

## Migration from FordLLM

Old way (Ford-internal):
```python
from services.ai_service import AIAnalysisService
ai = AIAnalysisService()  # Required Ford credentials
```

New way (Free, public):
```python
from services.ai_service import AIAnalysisService
ai = AIAnalysisService(provider="groq")  # Just need free API key
```

See `GROQ_MIGRATION_GUIDE.md` for more details.

---

**Start with Groq - it's free, fast, and powerful!** 🚀
