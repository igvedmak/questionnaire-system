FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency installs
RUN pip install --no-cache-dir uv

# Copy project files (pyproject first for layer caching)
COPY pyproject.toml .
COPY questionnaire/ questionnaire/

# Install core + analytics extras (no dev tools)
RUN uv venv /app/.venv && \
    uv pip install --python /app/.venv/bin/python -e ".[analytics]"

ENV PATH="/app/.venv/bin:$PATH"

# Data dir (SQLite DB + PII key mount point)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["qst", "api", "--host", "0.0.0.0", "--port", "8000"]
