"""
Groq API Integration Example
Simple example showing how to use Groq API for LLM operations
Free alternative to FordLLM
"""

import os
from dotenv import load_dotenv
from groq import Groq

# Load environment variables from .env file
load_dotenv(encoding='utf-8')


def main():
    """Main example function"""
    
    # Get API key from environment
    api_key = os.getenv("GROQ_API_KEY")
    
    if not api_key:
        print("Error: GROQ_API_KEY environment variable not set.")
        print("\nSetup Instructions:")
        print("1. Get a free API key from https://console.groq.com")
        print("2. Set environment variable: export GROQ_API_KEY='your_key_here'")
        print("   Or add to .env file: GROQ_API_KEY=your_key_here")
        return

    try:
        # Create Groq client
        client = Groq(api_key=api_key)
        
        print("✓ Connected to Groq API")
        print(f"✓ Using model: mixtral-8x7b-32768")
        
        # Example conversation
        messages = [
            {
                "role": "system",
                "content": "You are a helpful Java code analysis assistant."
            },
            {
                "role": "user",
                "content": "What are the top 5 best practices for Java migration to modern versions?"
            },
        ]

        print("\nSending request to Groq...")
        
        completion = client.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )

        response = completion.choices[0].message.content
        
        print("\n" + "="*60)
        print("RESPONSE:")
        print("="*60)
        print(response)
        print("="*60)
        
        # Print usage statistics
        print(f"\n📊 Token Usage:")
        print(f"  Prompt tokens: {completion.usage.prompt_tokens}")
        print(f"  Completion tokens: {completion.usage.completion_tokens}")
        print(f"  Total tokens: {completion.usage.total_tokens}")

    except Exception as e:
        print(f"✗ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Verify your API key is correct")
        print("2. Check your internet connection")
        print("3. Visit https://console.groq.com for status")


def analyze_code_example():
    """Example: Analyze Java code using Groq"""
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("GROQ_API_KEY not set")
        return
    
    client = Groq(api_key=api_key)
    
    java_code = """
    public class LegacyService {
        public void processOrder(Order order) {
            // Old Java 8 style code
            List<Item> items = order.getItems();
            for (Item item : items) {
                if (item.getPrice() > 0) {
                    total += item.getPrice();
                }
            }
        }
    }
    """
    
    messages = [
        {
            "role": "system",
            "content": "You are an expert Java code analyst. Provide analysis in JSON format."
        },
        {
            "role": "user",
            "content": f"""
            Analyze this Java code for modernization opportunities:
            
            {java_code}
            
            Return a JSON object with:
            - issues: list of code issues
            - recommendations: list of improvements
            - modern_alternatives: suggested Java 17+ improvements
            """
        }
    ]
    
    completion = client.chat.completions.create(
        model="mixtral-8x7b-32768",
        messages=messages,
        max_tokens=2048,
        temperature=0.3,  # Lower temperature for more focused analysis
    )
    
    print(completion.choices[0].message.content)


def list_available_models():
    """List Groq's available models"""
    models = [
        {
            "model_id": "mixtral-8x7b-32768",
            "name": "Mixtral 8x7B",
            "description": "Most capable open model (recommended)",
            "context_window": 32768,
            "cost_per_1m": "$0.20"
        },
        {
            "model_id": "llama-3.1-70b-versatile",
            "name": "Llama 3.1 70B",
            "description": "Large versatile model",
            "context_window": 8000,
            "cost_per_1m": "$0.20"
        },
        {
            "model_id": "llama-3.1-8b-instant",
            "name": "Llama 3.1 8B",
            "description": "Fast, compact model",
            "context_window": 8000,
            "cost_per_1m": "$0.20"
        },
        {
            "model_id": "gemma-7b-it",
            "name": "Gemma 7B",
            "description": "Compact instruction-tuned",
            "context_window": 8000,
            "cost_per_1m": "$0.20"
        }
    ]
    
    print("\nAvailable Groq Models:")
    print("="*80)
    for model in models:
        print(f"Model: {model['model_id']}")
        print(f"  Name: {model['name']}")
        print(f"  Description: {model['description']}")
        print(f"  Context Window: {model['context_window']} tokens")
        print(f"  Cost: {model['cost_per_1m']} per 1M tokens")
        print()


if __name__ == "__main__":
    print("="*60)
    print("Groq API Integration Example")
    print("="*60)
    
    main()
    
    # Uncomment to try other examples:
    # print("\n" + "="*60)
    # print("Code Analysis Example:")
    # print("="*60)
    # analyze_code_example()
    
    # print("\n" + "="*60)
    # list_available_models()
