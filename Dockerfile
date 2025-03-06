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

# Install pip tools first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install spaCy with specific version that has good wheel support for Python 3.9
RUN pip install --no-cache-dir --prefer-binary spacy==3.6.1

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Install other requirements
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy application code
COPY . .

# Command to run your application
CMD ["python", "bot.py"]
