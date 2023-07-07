web: gunicorn --max-requests 500 --max-requests-jitter 250 mapmonitor.wsgi
release: python manage.py migrate
tmx_scraper: python manage.py tmx_scraper
