FROM python:3.12-slim

# No .pyc files in the image; unbuffered output so `docker compose logs` is live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies layer. Only pyproject.toml is copied first, so this layer is
# rebuilt only when the dependency list changes, not on every code edit.
# The pinned runtime dependencies are read straight from pyproject.toml, so
# there is no second list to keep in sync.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# Application code. It runs from /app directly instead of being pip-installed.
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

# The app never needs root.
RUN useradd --create-home --uid 1000 navbat
USER navbat

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
