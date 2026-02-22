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

# Check for Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js first."
    exit 1
fi

# Install frontend dependencies if needed
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend
    npm install
    cd ..
fi

echo "🏁 Starting servers..."

# Start backend in background
echo "🐍 Starting Python backend server on http://localhost:5000..."
python app.py &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 3

# Start frontend
echo "⚛️  Starting React frontend server on http://localhost:3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!

# Function to cleanup on exit
cleanup() {
    echo "🛑 Shutting down servers..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID 2>/dev/null
    wait $FRONTEND_PID 2>/dev/null
    echo "✅ Servers stopped."
}

# Set up trap to cleanup on script exit
trap cleanup EXIT

echo ""
echo "✅ Both servers are starting up!"
echo "🌐 Frontend: http://localhost:3000"
echo "🔧 Backend API: http://localhost:5000"
echo ""
echo "📱 Your Sony TV Remote Control is ready!"
echo "Press Ctrl+C to stop both servers"
echo ""

# Wait for both processes
wait