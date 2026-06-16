import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

async def test_huggingface():
    api_key = os.getenv("HUGGINGFACE_API_KEY")
    if not api_key:
        print("❌ HUGGINGFACE_API_KEY not found in .env")
        return False

    # Try the router URL used in the backend
    url = "https://router.huggingface.co/hf-inference/models/mistralai/Mistral-7B-Instruct-v0.2"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"inputs": "Say hello!"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=15) as response:
                if response.status == 200:
                    print("✅ Hugging Face (Router): Connection successful")
                    return True
                else:
                    # Fallback to standard inference API
                    url = f"https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2"
                    async with session.post(url, headers=headers, json=payload, timeout=15) as response2:
                        if response2.status == 200:
                            print("✅ Hugging Face (Standard API): Connection successful")
                            return True
                        else:
                            text = await response2.text()
                            print(f"❌ Hugging Face: Status {response2.status}, Error: {text[:100]}")
                            return False
    except Exception as e:
        print(f"❌ Hugging Face: Exception: {e}")
        return False

async def test_openai():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in .env")
        return False

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Say hello!"}],
        "max_tokens": 10
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=15) as response:
                if response.status == 200:
                    print("✅ OpenAI: Connection successful")
                    return True
                else:
                    text = await response.text()
                    print(f"❌ OpenAI: Status {response.status}, Error: {text[:100]}")
                    return False
    except Exception as e:
        print(f"❌ OpenAI: Exception: {e}")
        return False

async def test_groq():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY not found in .env")
        return False

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": "Say hello!"}],
        "max_tokens": 10
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=15) as response:
                if response.status == 200:
                    print("✅ Groq: Connection successful")
                    return True
                else:
                    text = await response.text()
                    print(f"❌ Groq: Status {response.status}, Error: {text[:100]}")
                    return False
    except Exception as e:
        print(f"❌ Groq: Exception: {e}")
        return False

async def main():
    print("--- Verifying LLM Connections ---")
    await test_huggingface()
    await test_openai()
    await test_groq()
    print("--- Verification Complete ---")

if __name__ == "__main__":
    asyncio.run(main())
