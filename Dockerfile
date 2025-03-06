FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    gcc \
    g++ \
    git \
    cmake \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install packages that spaCy depends on first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel cython numpy

# Install spaCy separately with specific options
RUN pip install --no-cache-dir spacy==3.6.1 --no-build-isolation

# Install the rest of the requirements
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Copy application code
COPY . .

# Command to run your application
CMD ["python", "bot.py"]
