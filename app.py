from flask import Flask, request, jsonify
from flask_cors import CORS
import pytesseract
from PIL import Image
import fitz  # PyMuPDF
import os
import io
import cv2
import numpy as np
import requests
from dotenv import load_dotenv
import mysql.connector

# ========== MYSQL CONNECTION ==========
def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="vidyamnine"
    )

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = Flask(__name__)
CORS(app)

# Tesseract path (Windows)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Gemini API config
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
HEADERS = {
    "Content-Type": "application/json",
    "x-goog-api-key": GEMINI_API_KEY,
}

# ========== EXTRACT TEXT ==========
@app.route('/extract', methods=['POST'])
def extract_text():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    filename = file.filename.lower()

    try:
        if filename.endswith('.pdf'):
            doc = fitz.open(stream=file.read(), filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            return jsonify({'text': text.strip()})
        else:
            image = Image.open(file.stream).convert('RGB')
            image_np = np.array(image)
            gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
            text = pytesseract.image_to_string(gray)
            return jsonify({'text': text.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== GENERATE SOLUTION ==========
@app.route('/generate-solution', methods=['POST'])
def generate_solution():
    data = request.get_json()
    raw_text = data.get('question', '')

    if not raw_text.strip():
        return jsonify({'error': 'Empty question text'}), 400

    questions = [q.strip() for q in raw_text.strip().split('\n') if q.strip()]
    results = []

    try:
        conn = get_connection()
        cursor = conn.cursor()

        for q in questions:
            payload_solution = {
                "contents": [{
                    "parts": [{"text": f"Answer this educational question:\n\n{q}"}]
                }]
            }

            payload_hint = {
                "contents": [{
                    "parts": [{"text": f"Give a helpful hint for understanding or solving this question:\n\n{q}"}]
                }]
            }

            res_solution = requests.post(GEMINI_API_URL, headers=HEADERS, json=payload_solution)
            res_solution.raise_for_status()
            sol_text = res_solution.json()['candidates'][0]['content']['parts'][0]['text'].strip()

            res_hint = requests.post(GEMINI_API_URL, headers=HEADERS, json=payload_hint)
            res_hint.raise_for_status()
            hint_text = res_hint.json()['candidates'][0]['content']['parts'][0]['text'].strip()

            cursor.execute('''
                INSERT INTO extracted_data (question, solution, hint)
                VALUES (%s, %s, %s)
            ''', (q, sol_text, hint_text))

            results.append({
                'question': q,
                'solution': sol_text,
                'hint': hint_text
            })

        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'data': results})

    except Exception as e:
        print("Gemini API or DB Error:", e)
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ========== SAVE MANUALLY ==========
@app.route('/save-data', methods=['POST'])
def save_data():
    try:
        data = request.get_json()
        question = data.get('question')
        solution = data.get('solution')
        hint = data.get('hint', '')

        conn = get_connection()
        cursor = conn.cursor()
        sql = "INSERT INTO extracted_data (question, solution, hint) VALUES (%s, %s, %s)"
        cursor.execute(sql, (question, solution, hint))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "message": "Data saved to MySQL."})

    except Exception as e:
        print("MySQL Error:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

# ========== GET ALL SAVED SOLUTIONS ==========
@app.route('/get-solutions', methods=['GET'])
def get_solutions():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, question, solution, hint FROM extracted_data ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return jsonify({'status': 'success', 'data': rows})
    except Exception as e:
        print("Fetch Error:", e)
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ========== NEW: FETCH DATA FOR FLUTTER ==========
@app.route('/fetch-data', methods=['GET'])
def fetch_data():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM extracted_data ORDER BY id ASC")
        data = cursor.fetchall()
        conn.close()
        return jsonify(data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== MAIN ==========
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
