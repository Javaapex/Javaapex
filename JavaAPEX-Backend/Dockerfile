FROM python:3.11-slim-bookworm

ARG FOSSA_CLI_VERSION=3.16.0
ARG SONAR_SCANNER_VERSION=7.1.0.4889
ARG SONAR_SCANNER_SHA256=b4d2a001d65b489f9effe1ea8a78495db1b152f124d7f7b058aad8651c7e1484
ARG TEMURIN_API_BASE_URL=https://api.adoptium.net/v3/binary/latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    WORK_DIR=/tmp/migrations \
    JAVA_11_HOME=/opt/jdks/jdk-11 \
    JAVA_17_HOME=/opt/jdks/jdk-17 \
    JAVA_21_HOME=/opt/jdks/jdk-21 \
    JAVA_25_HOME=/opt/jdks/jdk-25 \
    JAVA_HOME=/opt/jdks/jdk-17 \
    PATH=/opt/jdks/jdk-17/bin:/usr/local/bin:${PATH}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    gradle \
    maven \
    tar \
    tini \
    unzip \
 && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    mkdir -p /opt/jdks; \
        for version in 11 17 21 25; do \
      archive="/tmp/jdk-${version}.tar.gz"; \
      target="/opt/jdks/jdk-${version}"; \
      curl -fsSL -o "${archive}" "${TEMURIN_API_BASE_URL}/${version}/ga/linux/x64/jdk/hotspot/normal/eclipse"; \
      mkdir -p "${target}"; \
      tar -xzf "${archive}" -C "${target}" --strip-components=1; \
      rm -f "${archive}"; \
      "${target}/bin/java" -version; \
    done

# Install modern Maven and Gradle
RUN set -eux; \
    # Install Maven 3.9.6
    curl -fsSL -o /tmp/maven.tar.gz https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz \
 && tar -xzf /tmp/maven.tar.gz -C /opt \
 && ln -sf /opt/apache-maven-3.9.6/bin/mvn /usr/local/bin/mvn \
 && rm -f /tmp/maven.tar.gz \
 && mvn -version; \
    # Install Gradle 8.7
    curl -fsSL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-8.7-bin.zip \
 && unzip -q /tmp/gradle.zip -d /opt \
 && ln -sf /opt/gradle-8.7/bin/gradle /usr/local/bin/gradle \
 && rm -f /tmp/gradle.zip \
 && gradle -version

RUN curl -fsSL -o /tmp/fossa.tar.gz \
    "https://github.com/fossas/fossa-cli/releases/download/v${FOSSA_CLI_VERSION}/fossa_${FOSSA_CLI_VERSION}_linux_amd64.tar.gz" \
 && tar -xzf /tmp/fossa.tar.gz -C /usr/local/bin fossa \
 && chmod 0755 /usr/local/bin/fossa \
 && rm -f /tmp/fossa.tar.gz \
 && /usr/local/bin/fossa --version

RUN curl -fsSL -o /tmp/sonar-scanner.zip \
    "https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux-x64.zip" \
 && echo "${SONAR_SCANNER_SHA256}  /tmp/sonar-scanner.zip" | sha256sum -c - \
 && unzip -q /tmp/sonar-scanner.zip -d /opt \
 && ln -sf "/opt/sonar-scanner-${SONAR_SCANNER_VERSION}-linux-x64/bin/sonar-scanner" /usr/local/bin/sonar-scanner \
 && rm -f /tmp/sonar-scanner.zip \
 && /usr/local/bin/sonar-scanner --version

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd --system appuser \
 && useradd --system --gid appuser --create-home --home-dir /home/appuser appuser \
 && mkdir -p /app/docker "${WORK_DIR}" \
 && chmod +x /app/docker/start-web.sh /app/docker/start-worker.sh \
 && chown -R appuser:appuser /app "${WORK_DIR}"

USER appuser

EXPOSE 10000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/docker/start-web.sh"]