import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

async def check_hf_token():
    api_key = os.getenv("HUGGINGFACE_API_KEY")
    print(f"\nChecking Hugging Face Token: {api_key[:10]}...")
    url = "https://huggingface.co/api/whoami-v2"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                print(f"✅ Hugging Face Token is VALID. User: {data.get('name')}")
                return True
            else:
                print(f"❌ Hugging Face Token is INVALID or EXPIRED. Status: {response.status}")
                return False

async def check_openai_token():
    api_key = os.getenv("OPENAI_API_KEY")
    print(f"\nChecking OpenAI Token: {api_key[:10]}...")
    url = "https://api.openai.com/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                print("✅ OpenAI Token is VALID and has access to models.")
                return True
            elif response.status == 429:
                print("⚠️ OpenAI Token is VALID, but you have NO QUOTA (Out of credits).")
                return False
            else:
                print(f"❌ OpenAI Token is INVALID or EXPIRED. Status: {response.status}")
                return False

async def main():
    print("=== Detailed Key Verification ===")
    await check_hf_token()
    await check_openai_token()

if __name__ == "__main__":
    asyncio.run(main())
