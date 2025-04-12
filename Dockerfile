FROM python:3.9-slim

WORKDIR /app

# Установка ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Установка зависимостей Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов
COPY run.py /app/
COPY .env.docker /app/.env
COPY modules/ /app/modules/

# Создание необходимых директорий
RUN mkdir -p /app/downloads /app/transcripts /app/recommendations /app/modules/api/templates /app/modules/api/static

# Точка входа
ENTRYPOINT ["python", "run.py"]
# Аргументы по умолчанию
CMD ["--web"] 