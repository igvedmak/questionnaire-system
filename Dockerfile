FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# --- Dependency layer (cached until pyproject.toml changes) ---------------
COPY pyproject.toml .

# Stub package lets uv resolve + download all deps without the real source.
# This layer is only invalidated when pyproject.toml changes (~170s first
# build, ~0s thereafter).
RUN uv venv /app/.venv && \
    mkdir -p questionnaire && \
    echo "" > questionnaire/__init__.py && \
    uv pip install --python /app/.venv/bin/python ".[analytics]" && \
    rm -rf questionnaire

# --- Source layer (fast re-install when only source changes) ---------------
COPY questionnaire/ questionnaire/

# Re-install the package itself without touching already-cached deps (~2s).
RUN uv pip install --python /app/.venv/bin/python --no-deps "."

ENV PATH="/app/.venv/bin:$PATH"

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["qst", "api", "--host", "0.0.0.0", "--port", "8000"]
