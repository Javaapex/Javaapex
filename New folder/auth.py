import os
import json
import time
from dotenv import load_dotenv

load_dotenv(encoding='utf-8')

TOKEN_CACHE_FILE = '.token_cache.json'


def get_access_token(force_refresh: bool = False) -> str:
    """Return API key from env and cache it for sample compatibility."""
    api_key = os.getenv('LLM_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError('LLM_API_KEY or OPENAI_API_KEY environment variable must be set.')

    if not force_refresh and os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            if time.time() - cache.get('timestamp', 0) < 3300 and cache.get('token'):
                return cache['token']
        except (OSError, json.JSONDecodeError):
            pass

    with open(TOKEN_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'token': api_key, 'timestamp': time.time()}, f)

    return api_key
