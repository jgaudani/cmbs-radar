# One image, four commands: cmbs-ingest, cmbs-score, cmbs-backtest, cmbs-api.
#   docker build -t cmbs-radar .
#   docker run --rm -e DATABASE_URL=... cmbs-radar cmbs-score

# The React UI, built into the api package.
FROM node:22-slim AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build   # writes ../src/cmbs_radar/api/web

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY --from=ui /app/src/cmbs_radar/api/web ./src/cmbs_radar/api/web
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home app
USER app
EXPOSE 8080
CMD ["cmbs-api", "--addr", ":8080"]
