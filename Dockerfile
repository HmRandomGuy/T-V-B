# Dockerfile for Txt-Voice-Bot (Koyeb Free Tier / Web Service)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install ffmpeg (required by pydub) and other runtime deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       libsndfile1 \
       ca-certificates \
       && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Expose default port (Koyeb routes usually supply a PORT env var)
EXPOSE 8080

# Start the bot in the background and run a small HTTP server so Koyeb treats this as a web app.
# Use PORT env var if present (set by platform) otherwise default to 8080.
CMD ["sh", "-c", "python bot.py & python -m http.server ${PORT:-8080}"]
