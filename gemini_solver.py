import requests
import os
from dotenv import load_dotenv

# Load API key from .env
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini 1.5 Flash endpoint
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
#GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent"

# Replace this with your own question for testing
sample_question = """
Explain the process of photosynthesis in plants.
"""

# Headers
headers = {
    "Content-Type": "application/json",
    "x-goog-api-key": GEMINI_API_KEY,
}

# Payload
payload = {
    "contents": [{
        "parts": [{"text": f"Answer this educational question:\n\n{sample_question}"}]
    }]
}

# Send request to Gemini API
try:
    response = requests.post(GEMINI_API_URL, headers=headers, json=payload)
    response.raise_for_status()
    result = response.json()
    solution_text = result['candidates'][0]['content']['parts'][0]['text']
    print("\n✅ AI-Generated Solution:\n")
    print(solution_text.strip())

except Exception as e:
    print("\n❌ Error fetching response from Gemini API:")
    print(e)
