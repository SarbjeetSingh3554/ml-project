# Use Python 3.10-slim: The standard for stable ML wheel bindings
FROM python:3.10-slim

# Prevent Python from writing .pyc files & buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Install minimal Linux system dependencies for OpenCV and Face Analysis
# libgl1 is the standard requirement for libGL.so.1 in modern Debian-slim images
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Upgrade pip and install requirements
# Using --no-cache-dir is critical to stay under 800MB
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose Railway's default port
EXPOSE 8080

# Run Gunicorn with gthread workers for CPU-bound ML stability on 1 CPU
# This avoids 'sync' worker timeouts during face matching
CMD ["sh", "-c", "gunicorn app:app --worker-class gthread --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT"]
