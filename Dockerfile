FROM python:3.12-slim

# System deps (optional but handy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for better cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy code
COPY app ./app

# Uvicorn will listen on 0.0.0.0:8000 (match ECS portMapping)
ENV PORT=8000
EXPOSE 8000

# Start server
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn","app.main:app","--host=0.0.0.0","--port=8000","--log-level","info","--proxy-headers"]