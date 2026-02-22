#!/bin/bash

# Sony TV Remote Control - Start Script
# This script starts both the Python backend and React frontend

echo "🚀 Starting Sony TV Remote Control..."

# Check if Python virtual environment exists
if [ ! -d ".venv" ]; then
    echo "⚠️  Python virtual environment not found. Creating one..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "📦 Activating Python virtual environment..."
source .venv/bin/activate

# Install Python dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "📦 Installing/updating Python dependencies..."
    pip install -r requirements.txt
fi

# Install Node.js dependencies
echo "📦 Syncing dependencies..."
yarn install

if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend && yarn install && cd ..
fi

echo "🏁 Starting servers with concurrently..."
echo "🌐 Frontend: http://localhost:3000"
echo "🔧 Backend API: http://localhost:5000"
echo ""

# Run concurrently via yarn
yarn start