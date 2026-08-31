# ReleaseGuard container image.
#
# Installs the releaseguard package (see pyproject.toml's
# [tool.setuptools.packages.find] -> include = ["app*"]) and ships the
# runtime code needed for both the API server and the CLI/eval harness.
FROM python:3.11-slim

WORKDIR /app

# Install system build essentials only if/when a dependency needs to compile;
# kept minimal on purpose. Uncomment if a future dependency requires it:
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Copy only what's needed to resolve the package build first, so Docker can
# cache the dependency-install layer across source-only changes.
COPY pyproject.toml ./
COPY requirements.lock ./

# Bring in the actual package source before installing, since setuptools
# needs app/ present to build the "releaseguard" distribution.
COPY app/ ./app/
COPY prompts/ ./prompts/
COPY eval/ ./eval/
COPY frontend/ ./frontend/
COPY .env.example ./

RUN pip install --no-cache-dir --requirement requirements.lock \
    && pip install --no-cache-dir --no-deps .

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
