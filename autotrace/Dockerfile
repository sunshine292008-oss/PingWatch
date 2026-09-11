FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY autotrace/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && playwright install --with-deps chromium
COPY autotrace ./autotrace

CMD ["uvicorn", "autotrace.api:app", "--host", "0.0.0.0", "--port", "8080"]