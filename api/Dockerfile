FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/api

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')"

# Client IP is resolved in-app against AURA_TRUSTED_PROXIES (api/netinfo.py), so
# uvicorn must not rewrite the socket peer from X-Forwarded-For behind our back.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
