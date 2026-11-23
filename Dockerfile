# Dockerfile for Invoice Extractor Suite

FROM python:3.13-slim

# Copy the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory to /app
WORKDIR /app

# Configurable: which app file to run (default: extractor_app.py)
ARG APP_FILE=extractor_app.py
ENV APP_FILE=${APP_FILE}
ENV PORT=8501

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy all application files from the repository
COPY . .

# Install Python dependencies using uv
# Using --system to install globally in the container's Python environment
RUN uv pip install --system -r requirements.txt

# Expose the Streamlit port
EXPOSE ${PORT}

# Configure health check
HEALTHCHECK CMD curl --fail http://localhost:${PORT}/_stcore/health

# Run the Streamlit application
ENTRYPOINT ["sh", "-c", "streamlit run ${APP_FILE} --server.port=${PORT} --server.address=0.0.0.0"]