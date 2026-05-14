# pip install --proxy http://internet.ford.com:83 --extra-index-url https://us-central1-python.pkg.dev/ford-e1efecf6706bfdab0dda9060/fordllm/simple/ fordllm-sdk openai

# Set Client id & secret in venv terminal:
# $env:FORDLLM_CLIENT_ID="e181xxxxxxxxxxxb904"
# $env:FORDLLM_CLIENT_SECRET="m8m8xxxxxxxxxxxxxxxxxxda9l"

import os
from dotenv import load_dotenv
from auth import get_access_token
from openai import OpenAI
import requests
from pprint import pprint

# Load environment variables from .env file
load_dotenv(encoding='utf-8')

def main():
    # Setup Proxy (as required for Ford network)
    os.environ["HTTP_PROXY"] = "http://internet.ford.com:83"
    os.environ["HTTPS_PROXY"] = "http://internet.ford.com:83"
    
    # Credentials check is now handled in get_access_token or remains here for UX
    if not os.getenv("FORDLLM_CLIENT_ID") or not os.getenv("FORDLLM_CLIENT_SECRET"):
        print("Error: Please set your Client ID and Secret.")
        return

    try:
        # 3. Get token (Cached internally in auth.py)
        access_token = get_access_token()

        def make_api_call(token):
            client = OpenAI(
                api_key=token,
                base_url="https://api.pivpn.core.ford.com/fordllmapi/api/v1",
            )
            
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "How many stars are in the universe?"},
            ]

            return client.chat.completions.create(
                model="fordllm-coding-model",
                messages=messages,
                extra_body={"models": ["gemini-2.5-pro"]}
            )

        try:
            completion = make_api_call(access_token)
        except Exception as e:
            # If we get an authentication error, try refreshing the token once
            if "401" in str(e) or "unauthorized" in str(e).lower():
                print("Token might be expired or invalid. Refreshing...")
                access_token = get_access_token(force_refresh=True)
                completion = make_api_call(access_token)
            else:
                raise e

        # # 6. Print the result
        print("\n--- Response ---")
        print(completion.choices[0].message.content)


        # # # 6. Get Models details
        # api_endpoint = "https://api.pivpn.core.ford.com/fordllmapi/api/v1/models_metadata"

        # response = requests.get(
        #     api_endpoint,
        #     headers={
        #         "Authorization": f"Bearer {access_token}"
        #     }
        # )

        # # Print the first model's metadata
        # example_model_metadata = response.json().get("data")
        # pprint(example_model_metadata)



    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
