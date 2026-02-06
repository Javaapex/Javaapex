#!/bin/bash

# Java Migration Accelerator Docker Startup Script

echo "🚀 Starting Java Migration Accelerator..."

# Set environment variables
export PYTHONPATH=/app/backend:$PYTHONPATH
export WORK_DIR=/tmp/migrations

# Create necessary directories
mkdir -p /tmp/migrations
mkdir -p /app/logs

# Function to handle graceful shutdown
cleanup() {
    echo "🛑 Shutting down Java Migration Accelerator..."
    kill 0
    exit 0
}

# Trap SIGTERM and SIGINT for graceful shutdown
trap cleanup SIGTERM SIGINT

echo "📊 Checking environment..."
echo "PYTHONPATH: $PYTHONPATH"
echo "WORK_DIR: $WORK_DIR"

# Start backend server in background
echo "🔧 Starting FastAPI backend server..."
cd /app/backend
python main.py &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 5

# Check if backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "❌ Backend failed to start"
    exit 1
fi

echo "✅ Backend started successfully (PID: $BACKEND_PID)"

# Start simple HTTP server for frontend in background
echo "🌐 Starting frontend HTTP server..."
cd /app/frontend/dist
python -m http.server 5173 &
FRONTEND_PID=$!

# Wait a moment for frontend to start
sleep 2

echo "✅ Frontend started successfully (PID: $FRONTEND_PID)"

# Health check function
health_check() {
    local max_attempts=30
    local attempt=1

    echo "🏥 Running health checks..."

    while [ $attempt -le $max_attempts ]; do
        if curl -f http://localhost:8001/health > /dev/null 2>&1; then
            echo "✅ Backend health check passed"
            return 0
        fi

        echo "⏳ Health check attempt $attempt/$max_attempts failed, retrying..."
        sleep 2
        ((attempt++))
    done

    echo "❌ Backend health check failed after $max_attempts attempts"
    return 1
}

# Run health check
if health_check; then
    echo "🎉 Java Migration Accelerator is ready!"
    echo "📍 Backend API: http://localhost:8001"
    echo "🌐 Frontend UI: http://localhost:5173"
    echo "📖 API Docs: http://localhost:8001/docs"
else
    echo "❌ Health check failed, shutting down..."
    cleanup
    exit 1
fi

echo ""
echo "=================================================="
echo "🚀 Java Migration Accelerator is LIVE!"
echo "=================================================="
echo "🌐 Frontend: http://localhost:5173"
echo "🔧 Backend:  http://localhost:8001"
echo "📖 API Docs: http://localhost:8001/docs"
echo "=================================================="
echo ""

# Keep container running and wait for processes
wait