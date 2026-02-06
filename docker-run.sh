#!/bin/bash

# Docker Run Script for Supply Bill Parser
# This script helps you run the project with Docker

echo "🐳 Starting Supply Bill Parser with Docker..."

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file from .env.docker template..."
    cp .env.docker .env
    echo "⚠️  Please edit .env file and add your API keys before running again!"
    echo "   Required: OPENAI_API_KEY"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Create necessary directories
mkdir -p storage/pdfs
mkdir -p bills_excel
mkdir -p bills_pdf
mkdir -p logs

echo "🏗️  Building and starting containers..."

# Build and run with docker-compose
docker-compose up --build

echo "🎉 Setup complete!"
echo ""
echo "📍 Services available at:"
echo "   🚀 API: http://localhost:8000"
echo "   📊 API Docs: http://localhost:8000/docs"
echo "   � Redis: localhost:6379"
echo ""
echo "📊 Using your remote MongoDB database"
echo ""
echo "To stop services: docker-compose down"
echo "To view logs: docker-compose logs -f"