FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    ffmpeg \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

RUN mkdir -p logs data archives voice_messages

CMD ["python", "bot.py"]