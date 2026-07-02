#!/bin/zsh

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

echo "Stopping database and removing its volume..."
docker compose down --volumes --remove-orphans

echo "Starting a fresh database container..."
docker compose up -d db

echo "Database reset complete."

