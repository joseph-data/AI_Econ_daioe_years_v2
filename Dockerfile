# ------------------------------- Builder Stage ------------------------------ #
FROM python:3.14-bookworm AS builder

# Install uv from official image (faster, reproducible, no curl needed)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install deps from lockfile (cache uv downloads for faster rebuilds).
# This is a flat Shiny app, so only install dependencies, not a package.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


## ------------------------------ Production Stage ---------------------------- ##
FROM python:3.14-slim-bookworm AS production

WORKDIR /app

# Environment set-up
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy only what the app needs at runtime
COPY app.py ./app.py
COPY src ./src
COPY data ./data
COPY logos ./logos
COPY md_files ./md_files
COPY _brand.yml ./_brand.yml

# Requirement for deployment at hf
EXPOSE 7860
CMD ["shiny", "run", "app.py", "--host", "0.0.0.0", "--port", "7860"]
