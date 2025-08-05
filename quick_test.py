# quick_test.py
import requests, os
from dotenv import load_dotenv

load_dotenv() 
key = os.getenv("GEMINI_API_KEY")
url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
headers = {
    "Content-Type": "application/json",
    "x-goog-api-key": key
}
body = {
    "contents": [
        {
            "parts": [
                {"text": "Why do we see lightning before thunder?"}
            ]
        }
    ]
}

r = requests.post(url, headers=headers, json=body)
print("Status code:", r.status_code)
print("Response body:", r.text)
