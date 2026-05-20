FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime

WORKDIR /opt
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser legacy/old-http-ml-architecture/libs/edu_ml_common /opt/libs/edu_ml_common
ENV PYTHONPATH=/opt/libs/edu_ml_common

COPY legacy/old-http-ml-architecture/services/task-generate/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY --chown=appuser:appuser legacy/old-http-ml-architecture/services/task-generate/task_svc /opt/svc/task_svc
COPY --chown=appuser:appuser legacy/old-http-ml-architecture/services/task-generate/app /opt/svc/app

WORKDIR /opt/svc
USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
