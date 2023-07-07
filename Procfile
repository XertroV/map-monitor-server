web: gunicorn --max-requests 100 --max-requests-jitter 80 mapmonitor.wsgi
release: python manage.py migrate
tmx_scraper: python manage.py tmx_scraper
