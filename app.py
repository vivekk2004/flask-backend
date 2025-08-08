# app.py
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

# -------------------------
# Load environment variables
# -------------------------
load_dotenv()

# -------------------------
# Configuration from env
# -------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = int(os.getenv("DB_PORT", 3306))
TESSERACT_CMD = os.getenv("TESSERACT_CMD")  # optional custom path

# -------------------------
# Configure tesseract path (if available)
# -------------------------
# Use custom TESSERACT_CMD if set; otherwise try common locations
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
else:
    # common Linux location
    if os.path.exists('/usr/bin/tesseract'):
        pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    # common Windows location (only applicable if running locally on Windows)
    elif os.path.exists(r'C:\Program Files\Tesseract-OCR\tesseract.exe'):
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    # else leave default (pytesseract will try to find it in PATH)

# -------------------------
# Gemini config
# -------------------------
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
HEADERS = {
    "Content-Type": "application/json",
    "x-goog-api-key": GEMINI_API_KEY or ""
}

# -------------------------
# Helper: create DB connection
# -------------------------
def get_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
        autocommit=False
    )

# -------------------------
# Flask app init
# -------------------------
app = Flask(__name__)
CORS(app)

# -------------------------
# Routes
# -------------------------

@app.route('/test-db', methods=['GET'])
def test_db():
    """Quick route to test DB connection"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DATABASE(), NOW()")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "database": row[0], "time": str(row[1])})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ========== EXTRACT TEXT ==========
@app.route('/extract', methods=['POST'])
def extract_text():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    filename = (file.filename or "").lower()

    try:
        if filename.endswith('.pdf'):
            # PDF handling via PyMuPDF
            doc = fitz.open(stream=file.read(), filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            return jsonify({'text': text.strip()})
        else:
            # Image handling
            image = Image.open(file.stream).convert('RGB')
            image_np = np.array(image)
            # convert to gray for better OCR
            gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
            text = pytesseract.image_to_string(gray)
            return jsonify({'text': text.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== GENERATE SOLUTION ==========
@app.route('/generate-solution', methods=['POST'])
def generate_solution():
    data = request.get_json() or {}
    raw_text = data.get('question', '')

    if not raw_text or not raw_text.strip():
        return jsonify({'error': 'Empty question text'}), 400

    questions = [q.strip() for q in raw_text.strip().split('\n') if q.strip()]
    results = []

    try:
        conn = get_connection()
        cursor = conn.cursor()

        for q in questions:
            # Prepare payloads
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

            # Call Gemini for solution
            res_solution = requests.post(GEMINI_API_URL, headers=HEADERS, json=payload_solution, timeout=60)
            res_solution.raise_for_status()
            sol_json = res_solution.json()
            sol_text = ""
            try:
                sol_text = sol_json['candidates'][0]['content']['parts'][0]['text'].strip()
            except Exception:
                sol_text = str(sol_json)

            # Call Gemini for hint
            res_hint = requests.post(GEMINI_API_URL, headers=HEADERS, json=payload_hint, timeout=60)
            res_hint.raise_for_status()
            hint_json = res_hint.json()
            hint_text = ""
            try:
                hint_text = hint_json['candidates'][0]['content']['parts'][0]['text'].strip()
            except Exception:
                hint_text = str(hint_json)

            # Insert into DB
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
        cursor.close()
        conn.close()

        return jsonify({'status': 'success', 'data': results})

    except requests.exceptions.RequestException as re:
        # network/Gemini errors
        return jsonify({'status': 'error', 'message': 'Gemini API request failed', 'details': str(re)}), 500
    except Exception as e:
        # DB or other errors
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ========== SAVE MANUALLY ==========
@app.route('/save-data', methods=['POST'])
def save_data():
    try:
        data = request.get_json() or {}
        question = data.get('question')
        solution = data.get('solution')
        hint = data.get('hint', '')

        if not question:
            return jsonify({"status": "error", "message": "Question is required"}), 400

        conn = get_connection()
        cursor = conn.cursor()
        sql = "INSERT INTO extracted_data (question, solution, hint) VALUES (%s, %s, %s)"
        cursor.execute(sql, (question, solution, hint))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"status": "success", "message": "Data saved to MySQL."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ========== GET ALL SAVED SOLUTIONS ==========
@app.route('/get-solutions', methods=['GET'])
def get_solutions():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, question, solution, hint FROM extracted_data ORDER BY id ASC")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({'status': 'success', 'data': rows})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ========== FETCH DATA FOR FLUTTER ==========
@app.route('/fetch-data', methods=['GET'])
def fetch_data():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM extracted_data ORDER BY id ASC")
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== MAIN ==========
if __name__ == '__main__':
    # When running locally you might want to set debug=True
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
