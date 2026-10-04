# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.14-trixie

WORKDIR /

# Arial-compatible fonts for rendering the social media share image to PNG
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

# Disable development dependencies
ENV UV_NO_DEV=1

WORKDIR /app
RUN uv sync --locked     && useradd --create-home appuser     && chown -R appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["uv", "run", "streamlit", "run", "main.py"]
CMD ["--server.port=8501"]