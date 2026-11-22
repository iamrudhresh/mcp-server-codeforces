# Codeforces MCP Server - Python runtime over Streamable HTTP.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY run_server.py .

# Run as an unprivileged user; the server needs no filesystem writes.
RUN useradd --create-home --uid 10001 mcp
USER mcp

EXPOSE 8000

# MCP endpoint: http://localhost:8000/mcp
# For STDIO instead: docker run -i --rm <image> python run_server.py
CMD ["python", "run_server.py", "--http", "--host", "0.0.0.0", "--port", "8000"]
