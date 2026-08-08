import requests

def call_ask_endpoint(question: str, base_url: str, timeout: int = 120) -> dict:
    response = requests.post(f"{base_url}/ask", json={"question": question}, timeout=timeout)
    response.raise_for_status()  
    return response.json()
