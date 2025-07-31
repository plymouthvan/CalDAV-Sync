# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy application code
COPY app/ ./app/
COPY .env.example .env

# Create data directory for SQLite database with proper permissions
RUN mkdir -p /app/data && chmod 777 /app/data && chown -R appuser:appuser /app

# Create entrypoint script to fix permissions at runtime
RUN echo '#!/bin/bash\n\
# Fix data directory permissions if needed\n\
if [ -d "/app/data" ]; then\n\
    chown -R appuser:appuser /app/data\n\
    chmod 755 /app/data\n\
fi\n\
# Switch to appuser and run the application\n\
exec su-exec appuser "$@"' > /entrypoint.sh && chmod +x /entrypoint.sh

# Install su-exec for user switching
RUN apt-get update && apt-get install -y su-exec && rm -rf /var/lib/apt/lists/*

# Use entrypoint script
ENTRYPOINT ["/entrypoint.sh"]

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/status')" || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
