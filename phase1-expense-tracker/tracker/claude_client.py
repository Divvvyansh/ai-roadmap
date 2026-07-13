import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

def get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Missing ANTHROPIC_API_KEY in .env")
    return Anthropic(api_key=api_key)