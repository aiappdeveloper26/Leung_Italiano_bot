# ── Italiano Bot — Dockerfile for Render free Web Service ──────────────────
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source
COPY italiano_bot.py .

# Render assigns a PORT env var; our keep-alive HTTP server reads it
ENV PORT=8080

EXPOSE 8080

CMD ["python", "italiano_bot.py"]
