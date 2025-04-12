"""
Конфигурация и константы для системы транскрибирования подкастов
"""

import os

# --- Пути к директориям и файлам ---
DOWNLOAD_DIR = "downloads"
TRANSCRIPT_DIR = "transcripts"
RECOMMENDATIONS_DIR = "recommendations"
DB_PATH = "database/radiot_advice.db"

# --- Настройки подкаста ---
RSS_URL = "https://radio-t.com/podcast.rss"
HOSTS = ["Umputun", "Bobuk", "Gray", "Ksenks", "Alek.sys"]

# Словарь алиасов для ведущих
HOST_ALIASES = {
    "Umputun": ["Умпутун", "Евгений", "Женя", "Жека", "Умпутун-Евгений", "Женис"],
    "Bobuk": ["Бобук", "Григорий", "Гриша", "Бобуков", "Боб", "Гриня", "Бобучелло"],
    "Gray": ["Грей", "Сергей", "Серёжа", "Сережа", "Серый", "Грэй"],
    "Ksenks": ["Ксенкс", "Ксения", "Ксюша", "Ксюха", "Ксю"],
    "Alek.sys": ["Алексис", "Алекс", "Александр", "Саша", "Алексей"]
}

# --- Настройки Whisper ---
WHISPER_MODEL = "large"  # Изменено с 'base' на 'large' для лучшего качества транскрипции

# --- Создание необходимых директорий ---
for directory in [DOWNLOAD_DIR, TRANSCRIPT_DIR, RECOMMENDATIONS_DIR, os.path.dirname(DB_PATH)]:
    os.makedirs(directory, exist_ok=True) 