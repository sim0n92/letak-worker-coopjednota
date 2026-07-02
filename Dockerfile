FROM python:3.12-alpine
WORKDIR /app

COPY manifest.json ./
COPY src/ ./src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Process reads its execute/terminate messages from stdin (see manifest.json)
ENTRYPOINT ["python", "src/main.py"]
