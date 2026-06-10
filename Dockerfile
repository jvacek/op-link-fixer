FROM ghcr.io/astral-sh/uv:python3.13-alpine

ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app.py ./

RUN addgroup -S app && adduser -S app -G app
USER app

# Tokens come from the runtime environment (k8s Secret) — no .env in the image.
# Socket Mode is outbound-only; nothing to EXPOSE.
CMD ["uv", "run", "--no-sync", "app.py"]
