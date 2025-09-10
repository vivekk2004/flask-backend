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
from mysql.connector import Error
from urllib.parse import urlparse

# Load local .env for development (ignored in production)
load_dotenv()

# Read keys from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

app = Flask(__name__)
CORS(app)

# Tesseract path (change if needed in your environment)
pytesseract.pytesseract.tesseract_cmd = "tesseract"
# If you need a Windows path:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
HEADERS = {"Content-Type": "application/json"}
if GEMINI_API_KEY:
    HEADERS["x-goog-api-key"] = GEMINI_API_KEY

# ---------- DB helpers ----------
def parse_database_url(url):
    """Parse mysql://user:pass@host:port/dbname"""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/") if parsed.path else None,
        "port": parsed.port or 3306
    }

def get_connection():
    """
    Build connection from DATABASE_URL or from DB_HOST/DB_USER/DB_PASSWORD/DB_NAME/DB_PORT
    IMPORTANT: do not store credentials in source. Set them as environment variables in Render.
    """
    try:
        if DATABASE_URL:
            cfg = parse_database_url(DATABASE_URL)
            host = cfg.get("host")
            user = cfg.get("user")
            password = cfg.get("password")
            database = cfg.get("database")
            port = cfg.get("port", 3306)
        else:
            host = os.getenv("DB_HOST", "localhost")
            user = os.getenv("DB_USER", "root")
            password = os.getenv("DB_PASSWORD", "")
            database = os.getenv("DB_NAME", "vidyamnine")
            port = int(os.getenv("DB_PORT", "3306"))

        conn_args = {
            "host": host,
            "user": user,
            "password": password,
            "database": database,
            "port": port,
            "connection_timeout": 10,
        }

        # Optional: auth plugin (if you get ER_NOT_SUPPORTED_AUTH_MODE)
        if os.getenv("DB_AUTH_PLUGIN"):
            conn_args["auth_plugin"] = os.getenv("DB_AUTH_PLUGIN")

        # Optional SSL args
        ssl_ca = os.getenv("DB_SSL_CA")
        ssl_cert = os.getenv("DB_SSL_CERT")
        ssl_key = os.getenv("DB_SSL_KEY")
        ssl_args = {}
        if ssl_ca:
            ssl_args["ssl_ca"] = ssl_ca
        if ssl_cert:
            ssl_args["ssl_cert"] = ssl_cert
        if ssl_key:
            ssl_args["ssl_key"] = ssl_key
        if ssl_args:
            conn_args.update(ssl_args)

        return mysql.connector.connect(**conn_args)

    except Error as e:
        raise Exception(f"MySQL connection error: {e}")

# ---------- Routes ----------
@app.route("/extract", methods=["POST"])
def extract_text():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    filename = file.filename.lower()

    try:
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=file.read(), filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            return jsonify({"text": text.strip()})
        else:
            image = Image.open(file.stream).convert("RGB")
            image_np = np.array(image)
            gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
            text = pytesseract.image_to_string(gray)
            return jsonify({"text": text.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/generate-solution", methods=["POST"])
def generate_solution():
    data = request.get_json() or {}
    raw_text = data.get("question", "")

    if not raw_text.strip():
        return jsonify({"error": "Empty question text"}), 400

    questions = [q.strip() for q in raw_text.strip().split("\n") if q.strip()]
    results = []
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        for q in questions:
            payload_solution = {"contents": [{"parts": [{"text": f"Answer this educational question:\n\n{q}"}]}]}
            payload_hint = {"contents": [{"parts": [{"text": f"Give a helpful hint for understanding or solving this question:\n\n{q}"}]}]}

            res_solution = requests.post(GEMINI_API_URL, headers=HEADERS, json=payload_solution)
            res_solution.raise_for_status()
            sol_text = res_solution.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

            res_hint = requests.post(GEMINI_API_URL, headers=HEADERS, json=payload_hint)
            res_hint.raise_for_status()
            hint_text = res_hint.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

            cursor.execute(
                "INSERT INTO extracted_data (question, solution, hint) VALUES (%s, %s, %s)",
                (q, sol_text, hint_text),
            )

            results.append({"question": q, "solution": sol_text, "hint": hint_text})

        conn.commit()
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        print("Gemini API or DB Error:", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass

@app.route("/save-data", methods=["POST"])
def save_data():
    conn = None
    cursor = None
    try:
        data = request.get_json() or {}
        question = data.get("question")
        solution = data.get("solution")
        hint = data.get("hint", "")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO extracted_data (question, solution, hint) VALUES (%s, %s, %s)",
                       (question, solution, hint))
        conn.commit()
        return jsonify({"status": "success", "message": "Data saved to MySQL."})
    except Exception as e:
        print("MySQL Error:", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass

@app.route("/get-solutions", methods=["GET"])
def get_solutions():
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, question, solution, hint FROM extracted_data ORDER BY id ASC")
        rows = cursor.fetchall()
        return jsonify({"status": "success", "data": rows})
    except Exception as e:
        print("Fetch Error:", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass

@app.route("/fetch-data", methods=["GET"])
def fetch_data():
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM extracted_data ORDER BY id ASC")
        data = cursor.fetchall()
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(debug=debug, host="0.0.0.0", port=port)
