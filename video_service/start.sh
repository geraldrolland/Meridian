#!/bin/bash
echo "Starting video service..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
