from dotenv import load_dotenv
from anthropic import Anthropic
import os


client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-sonnet-4-0",
    max_tokens=100,
    messages=[
        {"role": "user", "content": "What is the capital of India?"}
    ]
)

print(response.content[0].text)