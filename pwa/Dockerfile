# Standard library only - no pip install, nothing to pin, nothing to audit.
# On a single-user home network the dependency a service does not have is
# the one that cannot break at ten at night.
FROM python:3.12-alpine

RUN adduser -D -u 10001 prelude
WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static

ENV PRELUDE_APP=/app/static \
    PRELUDE_AUDIO=/data/audio \
    PRELUDE_SESSIONS=/data/sessions \
    PRELUDE_PORT=8080 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data/audio /data/sessions && chown -R prelude /data
USER prelude
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=4).status==200 else 1)"

CMD ["python3", "/app/server.py"]
