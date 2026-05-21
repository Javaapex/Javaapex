import os
from dotenv import load_dotenv
from auth import get_access_token
from openai import OpenAI

load_dotenv(encoding='utf-8')


def main() -> None:
    if not (os.getenv('LLM_API_KEY') or os.getenv('OPENAI_API_KEY')):
        print('Error: set LLM_API_KEY or OPENAI_API_KEY first.')
        return

    access_token = get_access_token()
    client = OpenAI(
        api_key=access_token,
        base_url=os.getenv('LLM_BASE_URL', os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')),
    )

    kwargs = {}
    sub_model = os.getenv('LLM_SUB_MODEL', '').strip()
    if sub_model:
        kwargs['extra_body'] = {'models': [sub_model]}

    completion = client.chat.completions.create(
        model=os.getenv('LLM_MODEL', os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')),
        messages=[
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': 'How many stars are in the universe?'},
        ],
        **kwargs,
    )

    print(completion.choices[0].message.content)


if __name__ == '__main__':
    main()
