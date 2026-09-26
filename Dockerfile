FROM python:3.11-slim

WORKDIR /app

# Install the package and its runtime dependencies.
COPY pyproject.toml ./
COPY packages ./packages
RUN pip install --no-cache-dir -e .

# Data directory for the SQLite database (mounted by compose).
RUN mkdir -p /app/data

CMD ["python", "-m", "packages.server.main"]