FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install ffmpeg (required by pydub) and other runtime deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY . /app

# Default command: run the bot worker
CMD ["python", "bot.py"]
