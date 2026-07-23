# Local development helpers for map-monitor-server.
# Prefer: `source .venv/bin/activate` then `just <recipe>`.

python := ".venv/bin/python"
pip := ".venv/bin/pip"

# Create .venv with Python 3.11 and install requirements.
venv:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ ! -d .venv ]]; then
      python3.11 -m venv .venv
    fi
    # Avoid ~/.local/bin/cc wrapper breaking psycopg2 builds.
    CC=/usr/bin/cc CXX=/usr/bin/c++ {{pip}} install -r requirements.txt

install: venv

# Start local Postgres (see DATABASE_URL in .env).
db-up:
    docker compose -f dev/docker-compose.yml up -d

db-down:
    docker compose -f dev/docker-compose.yml down

migrate:
    {{python}} manage.py migrate

run:
    {{python}} manage.py runserver 0.0.0.0:5000

cotd-worker:
    {{python}} manage.py cotd_quali_cache

tmx-scraper:
    {{python}} manage.py tmx_scraper

# Thin historical COTD ranking snapshots to ~1/min (dry-run by default).
thin-cotd-rankings *args:
    {{python}} manage.py thin_cotd_rankings {{args}}
