# LLM Implementation - Quick Start Code Examples

## 🚀 Quick Start Examples

### Example 1: Basic Code Analysis with Token Tracking

```python
from services.ai_service import AIAnalysisService
import asyncio

async def analyze_code():
    # Initialize with token tracking
    ai_service = AIAnalysisService(provider="groq")
    
    code_to_analyze = """
    public class OrderService {
        public void processOrder(Order order) {
            List<Item> items = order.getItems();
            for (Item item : items) {
                if (item.isValid()) {
                    processItem(item);
                }
            }
        }
    }
    """
    
    # Analyze with token tracking
    result = await ai_service.analyze_business_logic(
        code_content=code_to_analyze,
        file_path="OrderService.java"
    )
    
    # Print results
    print(f"Model Used: {result.model_used}")
    print(f"Issues Found: {len(result.issues_found)}")
    print(f"Recommendations: {result.recommendations}")
    print(f"Confidence: {result.confidence_score}")
    print(f"Tokens Used: {result.tokens}")
    
    # Check cumulative usage
    usage = ai_service.get_token_usage()
    print(f"Total Tokens: {usage['total_tokens']}")

asyncio.run(analyze_code())
```

### Example 2: Multi-Provider with Fallback

```python
from services.ai_service import LLMAnalysisService
import asyncio

async def analyze_with_fallback():
    # Service will fallback if primary unavailable
    service = LLMAnalysisService(
        provider_name="groq",
        enable_fallback=True
    )
    
    prompt = "Analyze this Java code for issues: ..."
    
    result = await service.generate_text(
        prompt=prompt,
        max_tokens=2048,
        temperature=0.3,
        system_prompt="You are an expert Java analyst."
    )
    
    # Check which provider was used
    print(f"Provider Used: {service.get_current_provider()}")
    print(f"Success: {result.get('success')}")
    print(f"Tokens: {result.get('tokens')}")
    
    if result.get("success"):
        print(result["generated_text"])

asyncio.run(analyze_with_fallback())
```

### Example 3: Check Provider Status

```python
from services.llm_config import LLMProviderConfig, LLMProvider
from services.ai_service import AIProviderFactory

# Print available providers
print("Available Providers:")
LLMProviderConfig.print_available_providers()

# Get configured providers
configured = LLMProviderConfig.get_configured_providers()
print(f"\nConfigured providers: {configured}")

# Get primary provider
primary = LLMProviderConfig.get_primary_provider()
print(f"Primary provider: {primary}")

# Get fallback chain
chain = LLMProviderConfig.get_fallback_chain()
print(f"Fallback chain: {chain}")

# Get available from factory
available = AIProviderFactory.get_available_providers()
print(f"Available (from factory): {available}")

# Get specific provider config
groq_config = LLMProviderConfig.get_provider_config(LLMProvider.GROQ)
print(f"\nGroq Config:")
for key, value in groq_config.items():
    print(f"  {key}: {value}")
```

### Example 4: Monitor Token Usage

```python
from services.groq_service import groq_service
import asyncio

async def track_token_usage():
    # Generate multiple responses
    for i in range(3):
        await groq_service.generate_text(
            prompt=f"Explain Java concept #{i}: ...",
            max_tokens=1024
        )
    
    # Get usage statistics
    usage = groq_service.get_token_usage()
    
    print("Token Usage Statistics:")
    print(f"  Total Requests: {usage['request_count']}")
    print(f"  Prompt Tokens: {usage['prompt_tokens']}")
    print(f"  Completion Tokens: {usage['completion_tokens']}")
    print(f"  Total Tokens: {usage['total_tokens']}")
    print(f"  Avg Tokens/Request: {usage['avg_tokens_per_request']:.0f}")
    
    # Reset if needed
    groq_service.reset_usage_tracking()
    print("\n✓ Token tracking reset")

asyncio.run(track_token_usage())
```

### Example 5: Groq Service Direct Usage

```python
from services.groq_service import groq_service
import asyncio

async def use_groq_directly():
    # 1. Generate text with async
    response = await groq_service.generate_text(
        prompt="What are best practices for Java migration?",
        max_tokens=2048,
        temperature=0.7,
        system_prompt="You are a Java migration expert."
    )
    
    print(f"Success: {response['success']}")
    print(f"Generated Text:\n{response['generated_text']}")
    print(f"Tokens: {response['tokens']}")
    
    # 2. Code analysis
    code_analysis = await groq_service.code_analysis(
        code="public class Example { ... }",
        analysis_type="security"  # or "general", "performance", "maintainability"
    )
    print(f"\nCode Analysis: {code_analysis}")
    
    # 3. Check availability
    is_available = groq_service.check_availability()
    print(f"\nGroq Available: {is_available}")
    
    # 4. Get model info
    models = groq_service.get_available_models()
    print(f"\nAvailable Models:")
    for model_id, info in models.items():
        print(f"  {model_id}: {info['desc']}")
    
    # 5. Get current usage
    usage = groq_service.get_token_usage()
    print(f"\nToken Usage: {usage}")

asyncio.run(use_groq_directly())
```

### Example 6: Error Handling

```python
from services.ai_service import AIAnalysisService, AIProviderFactory
import asyncio

async def handle_errors():
    try:
        # Initialize service
        ai_service = AIAnalysisService(provider="groq")
        
        code = "Your Java code here..."
        
        # Analyze with error handling
        result = await ai_service.analyze_business_logic(code)
        
        # Check result
        if not result.tokens:
            print("Warning: No token information returned")
        
        print(f"Analysis complete with {len(result.issues_found)} issues")
        
    except Exception as e:
        print(f"Error: {e}")
        # Fallback is already handled automatically
        print("Service will automatically use fallback provider")

asyncio.run(handle_errors())
```

### Example 7: Fast Batch Processing

```python
from services.groq_service import groq_service
import asyncio

async def batch_analysis():
    # Analyze multiple items concurrently
    items = [
        "public class Item1 { ... }",
        "public class Item2 { ... }",
        "public class Item3 { ... }",
    ]
    
    # Create tasks for concurrent execution
    tasks = [
        groq_service.generate_text(
            prompt=f"Analyze this code:\n{item}",
            max_tokens=1024
        )
        for item in items
    ]
    
    # Execute all concurrently
    results = await asyncio.gather(*tasks)
    
    # Process results
    successful = sum(1 for r in results if r.get("success"))
    total_tokens = sum(r.get("tokens", {}).get("total_tokens", 0) for r in results)
    
    print(f"Processed {len(results)} items")
    print(f"Successful: {successful}")
    print(f"Total tokens: {total_tokens}")

asyncio.run(batch_analysis())
```

### Example 8: Configuration and Setup

```python
import os
from dotenv import load_dotenv
from services.ai_service import AIProviderFactory, AIAnalysisService
from services.llm_config import LLMProviderConfig

# Load configuration
load_dotenv()

# Setup verification
def setup_verification():
    print("=== LLM Setup Verification ===\n")
    
    # 1. Check environment
    primary = os.getenv("LLM_PROVIDER", "groq")
    print(f"1. Primary Provider: {primary}")
    
    # 2. Check API keys
    providers_status = {
        "GROQ": bool(os.getenv("GROQ_API_KEY")),
        "OpenAI": bool(os.getenv("OPENAI_API_KEY")),
        "HuggingFace": bool(os.getenv("HUGGINGFACE_API_KEY")),
        "Ollama": bool(os.getenv("OLLAMA_URL")),
    }
    print("\n2. Configured Providers:")
    for provider, configured in providers_status.items():
        status = "✓ Configured" if configured else "✗ Not configured"
        print(f"   {provider}: {status}")
    
    # 3. Check available providers
    available = AIProviderFactory.get_available_providers()
    print(f"\n3. Available Providers: {available}")
    
    # 4. Print detailed config
    print("\n4. Provider Configurations:")
    for provider_name in ["groq", "openai", "huggingface"]:
        provider = AIProviderFactory.get_provider(provider_name)
        if provider:
            print(f"   ✓ {provider_name.upper()} available")
    
    # 5. Get fallback chain
    chain = LLMProviderConfig.get_fallback_chain()
    print(f"\n5. Fallback Chain: {chain}")
    
    print("\n=== Setup Complete ===")

setup_verification()
```

### Example 9: Cost Estimation

```python
from services.llm_config import LLMTokenCounter

# Create counter and track usage
counter = LLMTokenCounter()

# Simulate some usage
counter.add_usage("groq", 100, 50, 150)
counter.add_usage("groq", 200, 100, 300)
counter.add_usage("openai", 150, 50, 200)

# Get summary
summary = counter.get_usage_summary()
print("Usage Summary:")
print(f"  Total Tokens: {summary['total_tokens']}")
print(f"  Requests: {summary['request_count']}")
print(f"  Avg per Request: {summary['avg_tokens_per_request']:.0f}")

# Estimate costs
costs_per_1m = {
    "groq": 0.20,      # $0.20 per 30M tokens
    "openai": 0.50,    # $0.50 per 1M tokens (input)
}
costs = counter.estimate_cost(costs_per_1m)

print("\nEstimated Costs:")
for provider, cost in costs.items():
    print(f"  {provider}: ${cost:.4f}")

total_cost = sum(costs.values())
print(f"  Total: ${total_cost:.4f}")
```

### Example 10: FastAPI Integration

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from services.ai_service import AIAnalysisService
import asyncio

app = FastAPI()
ai_service = AIAnalysisService(provider="groq")

class CodeAnalysisRequest(BaseModel):
    code: str
    file_path: str = "unknown.java"

class CodeAnalysisResponse(BaseModel):
    success: bool
    model: str
    issues: int
    tokens: dict
    recommendations: list

@app.post("/analyze/business-logic")
async def analyze_business_logic(request: CodeAnalysisRequest) -> CodeAnalysisResponse:
    """Analyze Java code for business logic issues"""
    try:
        result = await ai_service.analyze_business_logic(
            code_content=request.code,
            file_path=request.file_path
        )
        
        return CodeAnalysisResponse(
            success=True,
            model=result.model_used,
            issues=len(result.issues_found),
            tokens=result.tokens or {},
            recommendations=result.recommendations
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/llm/usage")
async def get_llm_usage():
    """Get LLM token usage statistics"""
    usage = ai_service.get_token_usage()
    return {"token_usage": usage}

@app.get("/llm/status")
async def get_llm_status():
    """Get LLM provider status"""
    from services.ai_service import AIProviderFactory
    
    available = AIProviderFactory.get_available_providers()
    return {"available_providers": available}
```

## 📋 Common Patterns

### Pattern 1: Initialize Once, Reuse
```python
# In your module
ai_service = AIAnalysisService(provider="groq")

# Use multiple times (efficient)
result1 = await ai_service.analyze_business_logic(code1)
result2 = await ai_service.analyze_business_logic(code2)
```

### Pattern 2: Graceful Degradation
```python
service = LLMAnalysisService(enable_fallback=True)
result = await service.generate_text(prompt)

# Always returns valid result, even if all providers fail
if result.get("success"):
    print("Got response:", result["generated_text"])
else:
    print("Using fallback:", result["generated_text"])
```

### Pattern 3: Provider Switching
```python
# Easy to switch providers
for provider in ["groq", "openai", "ollama"]:
    service = AIAnalysisService(provider=provider)
    try:
        result = await service.analyze_business_logic(code)
        print(f"Success with {provider}")
        break
    except:
        print(f"Failed with {provider}, trying next...")
```

### Pattern 4: Monitor Tokens
```python
# Track expensive operations
result = await ai_service.analyze_business_logic(big_codebase)

if result.tokens and result.tokens["total_tokens"] > 4000:
    logger.warning(f"High token usage: {result.tokens['total_tokens']}")
```

## 🎯 Best Practices

```python
# ✓ DO: Use async/await
result = await ai_service.analyze_business_logic(code)

# ✗ DON'T: Use .run_in_executor() manually (already handled)

# ✓ DO: Check response success
if result.get("success"):
    print(result["generated_text"])

# ✓ DO: Use token tracking
usage = ai_service.get_token_usage()
log_to_analytics(usage)

# ✗ DON'T: Create new service instances unnecessarily
# Reuse: ai_service = AIAnalysisService()  # Once
# Use: await ai_service.analyze_business_logic(code)  # Many times

# ✓ DO: Let fallback work automatically
service = LLMAnalysisService(enable_fallback=True)

# ✓ DO: Configure providers in .env
# LLM_PROVIDER=groq
# GROQ_API_KEY=...
```

---

**Now you're ready to use the modernized LLM system!** 🚀
