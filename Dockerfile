FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

WORKDIR /app

# التبعيات أولاً للاستفادة من ذاكرة الطبقات
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# مجلدات قابلة للكتابة (اللوج + الإعدادات التي يعدّلها البوت)
RUN mkdir -p /app/logs

VOLUME ["/app/logs"]

CMD ["python", "main.py"]
