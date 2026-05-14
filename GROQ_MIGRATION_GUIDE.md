# FordLLM to Groq Migration Guide

## Overview

This project has been migrated from **FordLLM** (proprietary, Ford-internal LLM) to **Groq**, a freely available, high-speed LLM API. This change makes the project accessible to everyone without requiring Ford internal credentials.

## What Changed

### ❌ Removed
- `fordllm-sdk` dependency
- `fordllm_auth_service.py` (Ford-specific authentication)
- `New folder/auth.py` and `New folder/fordLLM.py` (Ford-specific examples)
- FordLLM proxy configuration (`http://internet.ford.com:83`)
- `FORDLLM_CLIENT_ID` and `FORDLLM_CLIENT_SECRET` environment variables

### ✅ Added
- **Groq Service** (`services/groq_service.py`) - Free, fast LLM API integration
- **Multi-Provider Architecture** - Support for multiple LLM providers
- **Groq Examples** (`New folder/groq_example.py`) - Usage examples
- **Configuration Guide** (`services/groq_config_guide.py`) - Setup instructions
- **Comprehensive `.env.example`** - Setup guide for all providers

## Quick Start (5 minutes)

### 1. Get Free Groq API Key

```bash
# Visit https://console.groq.com
# Sign up (free account, no credit card required)
# Go to API Keys section
# Copy your API key (looks like: gsk_...)
```

### 2. Create `.env` File

```bash
# Copy the example
cp .env.example .env

# Edit .env and add your Groq API key
GROQ_API_KEY=gsk_your_api_key_here
```

### 3. Install Dependencies

```bash
# Backend setup
cd JavaAPEX-Backend
pip install -r requirements.txt

# Or if using venv
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 4. Run the Application

```bash
python main.py
```

### 5. Access the API

```
http://localhost:8000/docs
```

## Supported LLM Providers

The application now supports multiple LLM providers. Set the provider via environment variable or API parameter:

### 1. **Groq** ⭐ RECOMMENDED (Free)
- **Setup**: Get API key from https://console.groq.com
- **Free Tier**: 100 requests/day, 30,000 requests/month
- **Speed**: Very fast (enterprise-grade inference)
- **Models**: Mixtral 8x7B (recommended), Llama 3.1, Gemma
- **Cost**: Free for development, $0.20 per 30M tokens for production

```bash
export GROQ_API_KEY=gsk_your_key_here
export GROQ_MODEL=mixtral-8x7b-32768
```

### 2. **HuggingFace** (Free with limits)
- **Setup**: Get token from https://huggingface.co/settings/tokens
- **Free Tier**: Rate limited but sufficient for development
- **Models**: Mistral, Zephyr, and many open-source options
- **Cost**: Free tier available

```bash
export HUGGINGFACE_API_KEY=hf_your_token_here
export HUGGINGFACE_TEST_MODELS=mistralai/Mistral-7B-Instruct-v0.3
```

### 3. **DeepSeek** (Free with registration)
- **Setup**: Get API key from https://www.deepseek.com/api
- **Free Tier**: Limited free credits
- **Models**: DeepSeek Coder and general models
- **Cost**: $0.14-$2.70 per 1M tokens

```bash
export DEEPSEEK_API_KEY=your_key_here
```

### 4. **Ollama** (Completely free - Local)
- **Setup**: Install from https://ollama.ai, run `ollama serve`
- **Free Tier**: Unlimited (runs locally on your machine)
- **Models**: Deepseek Coder, Llama, Mistral
- **Cost**: FREE - data never leaves your machine
- **Benefit**: Private, no API calls, perfect for testing

```bash
# Install and run
ollama pull deepseek-coder:6.7b-instruct
ollama serve

# Configure
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=deepseek-coder:6.7b-instruct
```

### 5. **OpenAI** (High quality, Paid)
- **Setup**: Get API key from https://platform.openai.com/api-keys
- **Free Tier**: None (requires credit card)
- **Models**: GPT-3.5-turbo, GPT-4
- **Cost**: GPT-3.5: $0.50-$1.50 per 1M tokens, GPT-4: $30-$60

```bash
export OPENAI_API_KEY=sk_your_key_here
export OPENAI_MODEL=gpt-3.5-turbo
```

## Migration Examples

### Before (FordLLM)
```python
from services.ai_service import AIAnalysisService

# Required Ford credentials
os.environ["FORDLLM_CLIENT_ID"] = "..."
os.environ["FORDLLM_CLIENT_SECRET"] = "..."

ai_service = AIAnalysisService()
result = await ai_service.analyze_business_logic(code)
```

### After (Groq - or any provider)
```python
from services.ai_service import AIAnalysisService

# Just set your free Groq API key
os.environ["GROQ_API_KEY"] = "gsk_..."

# Default provider is now Groq (free!)
ai_service = AIAnalysisService(provider="groq")
result = await ai_service.analyze_business_logic(code)

# Or choose another provider
ai_service = AIAnalysisService(provider="huggingface")  # Also free
ai_service = AIAnalysisService(provider="ollama")  # Completely free (local)
ai_service = AIAnalysisService(provider="openai")  # High quality (paid)
```

## Groq API Endpoints

### Available Models

```
✓ mixtral-8x7b-32768    (Recommended - most capable)
✓ llama-3.1-70b-versatile
✓ llama-3.1-8b-instant
✓ gemma-7b-it
```

### Usage Example

```python
from services.groq_service import groq_service

# Analyze code
result = await groq_service.code_analysis(
    code="public class MyClass { ... }",
    analysis_type="general"  # or "security", "performance", "maintainability"
)

# Generate text
result = await groq_service.generate_text(
    prompt="Explain this code...",
    max_tokens=2048,
    temperature=0.7
)
```

## Cost Comparison

| Provider | Free Tier | Paid Tier | Quality | Speed |
|----------|-----------|-----------|---------|-------|
| **Groq** | ✅ 100 req/day | $0.20/30M | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **HuggingFace** | ✅ Limited | Variable | ⭐⭐⭐ | ⭐⭐⭐ |
| **DeepSeek** | ✅ Limited | $0.14-$2.70 | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Ollama** | ✅ Unlimited | Free | ⭐⭐⭐ | ⭐⭐ |
| **OpenAI** | ❌ None | $0.50-$60 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

## Configuration Files

### Key Files Changed
1. **`main.py`** - Updated default provider from `fordllm` to `groq`
2. **`requirements`** - Removed `fordllm-sdk`, added `groq` and `openai`
3. **`services/ai_service.py`** - Removed `FordLLMAPI` class, added `AIProviderFactory` and `LLMAnalysisService`
4. **`services/groq_service.py`** - NEW: Groq-specific implementation
5. **`services/groq_config_guide.py`** - NEW: Setup and usage guide
6. **`.env.example`** - NEW: Comprehensive configuration template

### Environment Variables

See `.env.example` for all available options. Key variables:

```bash
# Groq (recommended)
GROQ_API_KEY=gsk_...
GROQ_MODEL=mixtral-8x7b-32768

# Alternative providers
OPENAI_API_KEY=sk_...
HUGGINGFACE_API_KEY=hf_...
DEEPSEEK_API_KEY=...
OLLAMA_URL=http://127.0.0.1:11434
```

## Troubleshooting

### "GROQ_API_KEY not set"
```bash
# Check if environment variable is set
echo $GROQ_API_KEY  # Linux/Mac
echo %GROQ_API_KEY%  # Windows

# Or add to .env file:
GROQ_API_KEY=gsk_your_key_here
```

### "Groq API request failed"
- Check your API key is correct
- Verify internet connection
- Check Groq status at https://status.groq.com

### Rate limiting
- Groq free tier: 100 requests/day
- Use Ollama for unlimited local testing
- Upgrade to paid tier for production

### Different models for different use cases

```python
# Fast responses - use smaller model
GROQ_MODEL=llama-3.1-8b-instant

# Better quality - use larger model
GROQ_MODEL=mixtral-8x7b-32768

# Local testing - use Ollama
OLLAMA_MODEL=deepseek-coder:6.7b-instruct
```

## Benefits of This Change

✅ **No Ford dependency** - Open to everyone  
✅ **Free to use** - Groq free tier is sufficient for development  
✅ **Fast** - Groq provides enterprise-grade inference speed  
✅ **Multiple providers** - Flexibility to choose provider  
✅ **Better architecture** - Cleaner, more maintainable code  
✅ **Community models** - Access to state-of-the-art open models  

## Next Steps

1. Get your free Groq API key from https://console.groq.com
2. Create `.env` file and add your API key
3. Install dependencies: `pip install -r requirements.txt`
4. Run the application: `python main.py`
5. Start using the Java migration tool!

## Support

For issues or questions:
- **Groq Issues**: https://console.groq.com/support
- **Project Issues**: Check the project README
- **Documentation**: See `services/groq_config_guide.py` and `.env.example`

---

**Happy coding! 🚀**
