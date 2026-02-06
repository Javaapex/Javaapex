# Multi-stage build: Frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY package*.json ./
RUN npm install
COPY . ./
RUN npm run build

# Backend stage
FROM python:3.11-slim
WORKDIR /app

# Install essential dependencies (including git)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    git \
    wget \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Download and install Java 17 (Eclipse Temurin) directly
RUN wget -q https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.11%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.11_9.tar.gz \
    && tar -xzf OpenJDK17U-jdk_x64_linux_hotspot_17.0.11_9.tar.gz -C /opt \
    && rm OpenJDK17U-jdk_x64_linux_hotspot_17.0.11_9.tar.gz

# Set Java environment
ENV JAVA_HOME=/opt/jdk-17.0.11+9
ENV PATH=$JAVA_HOME/bin:$PATH

# Download Maven directly
RUN wget -q https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz \
    && tar -xzf apache-maven-3.9.6-bin.tar.gz -C /opt \
    && rm apache-maven-3.9.6-bin.tar.gz

ENV MAVEN_HOME=/opt/apache-maven-3.9.6
ENV PATH=$MAVEN_HOME/bin:$PATH

# Copy backend files
COPY java-migration-backend/Java_Migration_Accelerator_backend/java-migration-backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY java-migration-backend/Java_Migration_Accelerator_backend/java-migration-backend/ .

# Copy built frontend from builder stage
COPY --from=frontend-builder /app/frontend/dist /app/static

# Create necessary directories
RUN mkdir -p /tmp/migrations /app/logs

# Expose ports (backend on 8001, frontend served via backend)
EXPOSE 8001

# Set environment variables
ENV PYTHONPATH=/app:$PYTHONPATH
ENV WORK_DIR=/tmp/migrations

# Start the backend server (it will serve static frontend files)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
