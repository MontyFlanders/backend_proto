# base Image
    FROM python:3.11-slim

    # Set working directory
    WORKDIR /app
    ENV PYTHONPATH="${PYTHONPATH}:/app"
    
    RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
    
    # Stage 2: Install Dependencies
    
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt


    # Stage 3: Copy Application
    
    COPY ./app ./app
    
    # Stage 4: Entrypoint control

    CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

    