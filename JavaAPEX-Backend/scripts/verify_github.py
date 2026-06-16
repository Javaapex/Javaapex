import os
from github import Github
from dotenv import load_dotenv

load_dotenv()

def test_github():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("❌ GITHUB_TOKEN not found in .env")
        return False

    try:
        g = Github(token)
        user = g.get_user()
        print(f"✅ GitHub: Connection successful. Authenticated as: {user.login}")
        return True
    except Exception as e:
        print(f"❌ GitHub: Exception: {e}")
        return False

if __name__ == "__main__":
    print("--- Verifying GitHub Connection ---")
    test_github()
    print("--- Verification Complete ---")
