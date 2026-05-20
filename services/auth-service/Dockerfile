FROM python:3.12-slim

WORKDIR /opt/svc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser libs/edu_ml_common /opt/libs/edu_ml_common
ENV PYTHONPATH=/opt/libs/edu_ml_common:/opt/svc

COPY services/auth-service/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY --chown=appuser:appuser services/auth-service/app /opt/svc/app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
