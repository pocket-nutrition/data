FROM python:3.15-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db/ ./db/
COPY loaders/ ./loaders/
COPY main.py .

RUN useradd -r -u 1001 appuser
USER appuser

ENTRYPOINT ["python", "main.py"]
# Default: run all loaders. Override with: --loader ciqual, --force, etc.
