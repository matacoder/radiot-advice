# Радио-Т Транскрибер

Сервис для автоматического скачивания, транскрибирования и анализа подкаста "Радио-Т" с извлечением упоминаемых продуктов и технологий.

## Возможности

- Скачивание подкастов из RSS-ленты
- Транскрибирование аудио с использованием модели OpenAI Whisper
- Извлечение упоминаемых продуктов и технологий из текста транскрипции
- Консольный интерфейс для управления
- Веб-интерфейс на базе FastAPI

## Требования

- Python 3.9+
- FFmpeg (для обработки аудио)
- OpenAI API ключ (для анализа текста)
- Зависимости Python из requirements.txt

## Установка

1. Клонировать репозиторий:
```bash
git clone https://github.com/yourusername/radiot-advice.git
cd radiot-advice
```

2. Установить зависимости:
```bash
pip install -r requirements.txt
```

3. Установить FFmpeg (если не установлен):
   - Windows: с [официального сайта](https://www.gyan.dev/ffmpeg/builds/) или `choco install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt install ffmpeg`

4. Создать файл `.env` с ключом API OpenAI:
```
OPENAI_API_KEY=your_openai_api_key
```

## Использование

### Консольный интерфейс

```bash
python run.py --console
```

### Веб-интерфейс

```bash
python run.py --web
```

### Прямая обработка определенного эпизода

```bash
python run.py --process 123 # обработать эпизод #123
```

Для принудительного обновления транскрипции используйте флаг `--force-retranscribe`:

```bash
python run.py --process 123 --force-retranscribe
```

## Структура проекта

- `modules/` - основной код проекта
  - `core/` - основная функциональность по обработке подкастов
  - `api/` - веб-интерфейс на FastAPI
  - `console/` - консольный интерфейс
  - `utils/` - вспомогательные функции
- `downloads/` - скачанные аудиофайлы
- `transcripts/` - текстовые транскрипции
- `recommendations/` - извлеченная информация о продуктах

## Docker

Проект можно запустить с использованием Docker:

```bash
docker-compose up
```

## Лицензия

MIT 