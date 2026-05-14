import os
import json
import time
from dotenv import load_dotenv
from fordllm.utils import TokenFetcher

# Load environment variables from .env file
load_dotenv(encoding='utf-8')

TOKEN_CACHE_FILE = ".token_cache.json"

def get_access_token(force_refresh=False):
    """
    Fetches the access token, using a local cache if it is still valid.
    Set force_refresh=True to bypass the cache.
    """
    # 1. Setup Proxy (as required for Ford network)
    os.environ["HTTP_PROXY"] = "http://internet.ford.com:83"
    os.environ["HTTPS_PROXY"] = "http://internet.ford.com:83"

    # 2. Get Credentials
    client_id = os.getenv("FORDLLM_CLIENT_ID")
    client_secret = os.getenv("FORDLLM_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError("FORDLLM_CLIENT_ID and FORDLLM_CLIENT_SECRET environment variables must be set.")

    # 3. Check Cache
    if not force_refresh and os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r") as f:
                cache = json.load(f)
            
            # Use 55 minutes (3300 seconds) as a buffer for the 1 hour expiry
            if time.time() - cache["timestamp"] < 3300:
                print("Using cached access token...")
                return cache["token"]
        except (KeyError, json.JSONDecodeError):
            print("Malformed cache file. Re-fetching token...")
            pass

    # 4. Fetch New Token
    try:
        print("Fetching new access token...")
        token_fetcher = TokenFetcher(client_id=client_id, client_secret=client_secret)
        token = token_fetcher.token
        
        if not token:
            raise ValueError("Fetched token is empty. Check your credentials or network.")

        # 5. Save to Cache
        with open(TOKEN_CACHE_FILE, "w") as f:
            json.dump({
                "token": token,
                "timestamp": time.time()
            }, f)

        return token
    except Exception as e:
        # If token fetching fails, clear the cache and raise the error
        if os.path.exists(TOKEN_CACHE_FILE):
            os.remove(TOKEN_CACHE_FILE)
        raise RuntimeError(f"Failed to fetch FordLLM token: {e}")

