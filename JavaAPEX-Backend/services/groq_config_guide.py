"""
Groq Configuration and Usage Examples
Free, high-speed LLM API for Java migration analysis
"""

"""
SETUP INSTRUCTIONS:

1. Get a free Groq API key:
   - Visit https://console.groq.com
   - Sign up for a free account
   - Navigate to API Keys section
   - Copy your API key

2. Set environment variables in your .env file or system:
   GROQ_API_KEY=your_api_key_here
   GROQ_MODEL=mixtral-8x7b-32768  # or other available models

3. Available Models:
   - mixtral-8x7b-32768 (recommended, most capable)
   - llama-3.1-70b-versatile (good for code analysis)
   - llama-3.1-8b-instant (faster, smaller)
   - gemma-7b-it (compact model)

USAGE EXAMPLES:
"""

# Example 1: Using Groq service directly
async def example_groq_analysis():
    from services.groq_service import groq_service
    
    code = '''
    public class Example {
        public int calculate(int a, int b) {
            return a + b;
        }
    }
    '''
    
    result = await groq_service.code_analysis(code, analysis_type="general")
    print(result)


# Example 2: Using LLM Analysis Service with Groq
async def example_llm_service():
    from services.ai_service import LLMAnalysisService
    
    service = LLMAnalysisService(provider_name="groq")
    
    prompt = "Analyze this Java code for bugs..."
    result = await service.generate_text(
        prompt=prompt,
        max_tokens=2048,
        temperature=0.7
    )
    print(result)


# Example 3: Using AI Analysis Service for Java migration
async def example_ai_analysis():
    from services.ai_service import AIAnalysisService
    
    ai_service = AIAnalysisService(provider="groq")
    
    java_code = """
    public class LegacyService {
        public void processData() {
            // Old Java style code
        }
    }
    """
    
    result = await ai_service.analyze_business_logic(java_code, "LegacyService.java")
    print(result)


# Example 4: Configure different providers
async def example_multiple_providers():
    from services.ai_service import AIAnalysisService
    
    # Use Groq (free)
    groq_service = AIAnalysisService(provider="groq")
    
    # Or use OpenAI (requires API key)
    # openai_service = AIAnalysisService(provider="openai")
    
    # Or use HuggingFace (free with limitations)
    # hf_service = AIAnalysisService(provider="huggingface")
    
    # Use the service
    result = await groq_service.analyze_business_logic(code, "file.java")


"""
COST COMPARISON:

1. Groq (RECOMMENDED FOR THIS PROJECT):
   - Free tier: 100 requests/day
   - Paid: 30M tokens/month for $0.20
   - Speed: Very fast (blazing fast inference)
   - Models: Mixtral 8x7B, Llama 3.1, Gemma

2. OpenAI:
   - GPT-3.5-Turbo: $0.50/$1.50 per 1M tokens
   - GPT-4: $30/$60 per 1M tokens
   - No free tier currently
   - Highest quality

3. HuggingFace:
   - Free with rate limits
   - Serverless inference API
   - Limited to specific models
   - Good for development

4. Ollama (Local):
   - Free, runs locally
   - No API costs
   - Slower inference
   - Good for testing

RECOMMENDATION:
Use Groq as the default provider for this project because:
✓ Free tier is sufficient for development
✓ Very fast inference (enterprise-grade)
✓ Good quality open-source models (Mixtral, Llama)
✓ Easy to set up
✓ No credit card required for basic usage
"""


def get_groq_models():
    """Get list of available Groq models"""
    return [
        {
            "id": "mixtral-8x7b-32768",
            "name": "Mixtral 8x7B",
            "description": "Most capable open model, recommended",
            "context": 32768,
            "speed": "Very Fast"
        },
        {
            "id": "llama-3.1-70b-versatile",
            "name": "Llama 3.1 70B",
            "description": "Large, versatile model",
            "context": 8000,
            "speed": "Fast"
        },
        {
            "id": "llama-3.1-8b-instant",
            "name": "Llama 3.1 8B",
            "description": "Smaller, faster model",
            "context": 8000,
            "speed": "Very Fast"
        },
        {
            "id": "gemma-7b-it",
            "name": "Gemma 7B",
            "description": "Compact instruction-tuned model",
            "context": 8000,
            "speed": "Very Fast"
        }
    ]


def print_groq_setup_guide():
    """Print setup guide for Groq"""
    guide = """
╔════════════════════════════════════════════════════════════╗
║           GROQ API SETUP GUIDE                            ║
╚════════════════════════════════════════════════════════════╝

STEP 1: Get API Key
  1. Visit https://console.groq.com
  2. Create account
  3. Go to API Keys
  4. Generate new key
  5. Copy your key (starts with 'gsk_')

STEP 2: Install Python Package
  pip install groq

STEP 3: Set Environment Variable
  - Windows (PowerShell):
    $env:GROQ_API_KEY="gsk_your_key_here"
  
  - Linux/Mac:
    export GROQ_API_KEY="gsk_your_key_here"
  
  - Or add to .env file:
    GROQ_API_KEY=gsk_your_key_here

STEP 4: Verify Setup
  python -c "from groq import Groq; print('Groq installed successfully')"

STEP 5: Start Using!
  The project will automatically use Groq as the default LLM provider.

═══════════════════════════════════════════════════════════════

FREE TIER LIMITS:
  - 100 requests per day
  - 30,000 requests per month
  - Sufficient for development and testing

UPGRADE TO PAID:
  https://console.groq.com/billing
  Starting at $0.20 per 30M tokens
═══════════════════════════════════════════════════════════════
    """
    print(guide)
