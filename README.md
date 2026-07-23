# map-monitor-server

## Local setup

```bash
just venv                 # Python 3.11 .venv + requirements
cp mapmonitor/.env.example .env   # or use the generated .env; set MAP_MONITOR_LOCAL_DEV=True
just db-up                # local Postgres via docker compose
# Redis on 127.0.0.1:6379 required for COTD live cache (REDIS_URL)
just migrate
just run                  # http://0.0.0.0:5000
```

Activate the venv with `source .venv/bin/activate` if you prefer running `manage.py` directly.

Other recipes: `just cotd-worker`, `just tmx-scraper`, `just thin-cotd-rankings --dry-run`.

Copy auth/S3 example files (`.openplanet-auth`, `.dedi-server-acct`, `.s3`, etc.) when calling Nadeo/S3.
