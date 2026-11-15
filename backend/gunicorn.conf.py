import os

wsgi_app = "config.wsgi:application"
bind = "0.0.0.0:8000"  # the port set for the app in the ParsPack panel
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = 60
accesslog = "-"
errorlog = "-"
