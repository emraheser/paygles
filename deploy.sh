#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "❌ docker bulunamadı. Önce Docker kur."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "❌ docker compose bulunamadı. Docker Compose eklentisini kur."
  exit 1
fi

if [ ! -f "./backend/.env" ]; then
  echo "❌ backend/.env bulunamadı."
  echo "   Örnek: cp backend/.env.example backend/.env"
  exit 1
fi

echo "🔨 Building containers..."
docker compose build

echo "🚀 Starting services..."
docker compose up -d

echo "📦 Running containers:"
docker compose ps

echo ""
echo "═══════════════════════════════════════"
echo "✅ VPS deployment complete!"
echo "   Frontend: http://<sunucu-ip>:3000"
echo "   Backend:  http://<sunucu-ip>:8000/health"
echo "═══════════════════════════════════════"
