FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Upgrade pip, setuptools, and wheel
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install NumPy first (to avoid binary incompatibility with SpaCy)
RUN pip install --no-cache-dir --prefer-binary numpy==1.23.5

# Install spaCy with a version that has stable wheels for Python 3.9
RUN pip install --no-cache-dir --prefer-binary spacy==3.5.4

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Install other requirements
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy application code
COPY . .

# Command to run your application
CMD ["python", "bot.py"]
