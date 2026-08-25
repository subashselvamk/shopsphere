FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY api-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API gateway code
COPY api-gateway/main.py .

# Copy frontend directory
COPY frontend ./frontend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]