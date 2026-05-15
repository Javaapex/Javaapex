FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    WORK_DIR=/tmp/migrations

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    gradle \
    maven \
    tar \
    unzip \
    default-jdk-headless \
 && rm -rf /var/lib/apt/lists/*

# Install FOSSA CLI during image build so Render runtime has it available on PATH.
# Official install guidance uses the install-latest.sh script.
RUN curl -H 'Cache-Control: no-cache' https://raw.githubusercontent.com/fossas/fossa-cli/master/install-latest.sh \
    | BINDIR=/usr/local/bin bash \
 && /usr/local/bin/fossa --version

# Install SonarScanner CLI for SonarCloud/SonarQube analysis.
# Source: SonarSource Linux x64 distribution.
RUN curl -fsSL -o /tmp/sonar-scanner.zip \
    https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-7.1.0.4889-linux-x64.zip \
 && unzip -q /tmp/sonar-scanner.zip -d /opt \
 && ln -sf /opt/sonar-scanner-7.1.0.4889-linux-x64/bin/sonar-scanner /usr/local/bin/sonar-scanner \
 && rm -f /tmp/sonar-scanner.zip \
 && /usr/local/bin/sonar-scanner --version

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

# Set environment variables for large file uploads on DigitalOcean (up to 1GB+ files)
ENV UVICORN_MAX_REQUEST_SIZE=1500MB
ENV UVICORN_MAX_REQUESTS=1000
ENV UVICORN_TIMEOUT_KEEP_ALIVE=300
ENV UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=30

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --limit-concurrency 100 --limit-max-requests 1000 --timeout-keep-alive 300 --timeout-graceful-shutdown 30 --h11-max-incomplete-event-size 1073741824"]
