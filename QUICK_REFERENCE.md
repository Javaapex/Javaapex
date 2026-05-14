# 🚀 Quick Reference: Using Groq with JavaAPEX

## 60-Second Setup

```bash
# 1. Get API key (visit https://console.groq.com, sign up, copy key)
# 2. Set environment variable
export GROQ_API_KEY=gsk_your_key_here

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run application
python main.py

# 5. Use API at http://localhost:8000/docs
```

## Code Examples

### Example 1: Analyze Java Code
```python
from services.ai_service import AIAnalysisService

ai = AIAnalysisService(provider="groq")

code = """
public class OrderService {
    public void processOrder(Order order) {
        List<Item> items = order.getItems();
        for (Item item : items) {
            if (item.isValid()) {
                saveItem(item);
            }
        }
    }
}
"""

result = await ai.analyze_business_logic(code, "OrderService.java")
print(result)
```

### Example 2: Use Groq Service Directly
```python
from services.groq_service import groq_service

# Analyze for security issues
result = await groq_service.code_analysis(code, "security")

# Generate text
result = await groq_service.generate_text(
    prompt="Explain this Java pattern...",
    max_tokens=2048
)
```

### Example 3: API Endpoint
```bash
# Via REST API
curl -X POST http://localhost:8000/api/migration/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "llm_test_provider": "groq",
    "repository_url": "https://github.com/user/repo"
  }'
```

## Environment Variables

```bash
# ✅ REQUIRED
GROQ_API_KEY=gsk_...

# Optional (defaults provided)
GROQ_MODEL=mixtral-8x7b-32768
GROQ_BASE_URL=https://api.groq.com/openai/v1

# Global
LLM_TEST_PROVIDER=groq
```

## Available Groq Models

```python
# Fast & Capable
GROQ_MODEL=mixtral-8x7b-32768      # ⭐ RECOMMENDED

# Large & Versatile
GROQ_MODEL=llama-3.1-70b-versatile

# Fast & Compact
GROQ_MODEL=llama-3.1-8b-instant

# Small & Efficient
GROQ_MODEL=gemma-7b-it
```

## Switch Providers

```python
# Groq (free) ⭐
ai = AIAnalysisService(provider="groq")

# OpenAI (paid, high quality)
ai = AIAnalysisService(provider="openai")

# HuggingFace (free, limited)
ai = AIAnalysisService(provider="huggingface")

# Ollama (local, completely free)
ai = AIAnalysisService(provider="ollama")
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "API key not set" | Set `GROQ_API_KEY` in .env |
| "Connection failed" | Check internet, verify API key |
| "Rate limit" | Free tier: 100/day. Use Ollama for unlimited |
| "Model not found" | Use `mixtral-8x7b-32768` (default) |

## Where to Find Things

| Item | Location |
|------|----------|
| Setup guide | `GROQ_MIGRATION_GUIDE.md` |
| Provider docs | `LLM_PROVIDERS_GUIDE.md` |
| Config example | `.env.example` |
| Groq service | `services/groq_service.py` |
| AI service | `services/ai_service.py` |
| Python examples | `New folder/groq_example.py` |

## Cost

- **Groq Free**: $0/month (100 requests/day)
- **Groq Paid**: $0.20 per 30M tokens
- **OpenAI**: $0.50-60 per 1M tokens
- **HuggingFace**: Free/variable
- **Ollama**: Free (local)

## Key Services

```python
# Groq service (fast, free)
from services.groq_service import groq_service

# AI analysis service (multi-provider)
from services.ai_service import AIAnalysisService

# LLM service (provider abstraction)
from services.ai_service import LLMAnalysisService

# Migration service (uses LLM)
from services.migration_service import migration_service
```

## Recommended Settings

### Development (Free)
```bash
GROQ_API_KEY=gsk_...
GROQ_MODEL=mixtral-8x7b-32768
LLM_TEST_PROVIDER=groq
```

### Production (Cost-Effective)
```bash
GROQ_API_KEY=gsk_...  # Groq paid tier
GROQ_MODEL=mixtral-8x7b-32768
LLM_TEST_PROVIDER=groq
```

### Testing (No Costs, Slow)
```bash
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=deepseek-coder
LLM_TEST_PROVIDER=ollama
```

---

**Get your free Groq API key at https://console.groq.com** 🎉
