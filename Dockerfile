FROM python:3.10-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y tesseract-ocr libglib2.0-0 libsm6 libxext6 libxrender-dev libpoppler-cpp-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Run the app
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
