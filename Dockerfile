FROM python:3.11-slim
WORKDIR /app
COPY entity-resolution/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY entity-resolution/ .
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 app:app
