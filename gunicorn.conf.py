import os

bind = '0.0.0.0:5000'
workers = int(os.getenv('WEB_CONCURRENCY', '2'))
threads = int(os.getenv('GUNICORN_THREADS', '4'))
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
errorlog = '-'
accesslog = '-'
# Deliberately omit the query string, request bodies and headers (tokens, OTP).
access_log_format = '%(t)s %(m)s %(U)s %(s)s %(L)s'
forwarded_allow_ips = ''
