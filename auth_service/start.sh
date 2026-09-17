#!/bin/sh
echo "Running migrations..."
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f migrations/001_create_users.sql
echo "Starting server..."
node dist/server.js
