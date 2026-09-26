#!/bin/bash
# PathDrift initialization script
# Run this once after cloning and setting up .env

set -e

echo "=== PathDrift Setup Script ==="
echo ""

# Check .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found."
    echo "Run: cp .env.example .env"
    echo "Then edit .env and set POSTGRES_PASSWORD, REDIS_PASSWORD, SECRET_KEY"
    exit 1
fi

echo "1. Starting database and Redis..."
docker-compose up -d db redis

echo "Waiting for PostgreSQL to be ready..."
sleep 5

echo "2. Running database migrations..."
docker-compose run --rm backend alembic upgrade head

echo "3. Seeding orthology data (this may take a minute)..."
docker-compose run --rm backend python scripts/seed_orthology.py

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Start all services: docker-compose up -d"
echo "Frontend:           http://localhost:3000"
echo "Backend API docs:   http://localhost:8000/api/docs"
echo "Celery Flower:      http://localhost:5555"
