"""
Вспомогательные функции для работы с подкастами
"""

import os
import re
import json
import logging

logger = logging.getLogger(__name__)

try:
    import openai
except ImportError:
    logger.error("Библиотека openai не установлена. Установите её с помощью pip install openai")

def load_api_key():
    """Загрузка API ключа из .env файла (для анализа текста)"""
    api_key = None
    
    # Попытка загрузить из .env файла
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.strip().split("=", 1)[1]
                        break
        except Exception as e:
            logger.error(f"Ошибка при чтении файла .env: {str(e)}")
    
    # Если ключ не найден, проверяем в переменных окружения
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    
    # Если ключ всё еще не найден, запросить у пользователя
    if not api_key:
        logger.warning("API ключ OpenAI не найден в .env файле или переменных окружения")
        api_key = input("Введите ваш API ключ OpenAI для анализа текста: ")
    
    return api_key

def check_openai_api_key(api_key):
    """Проверяет работоспособность API ключа OpenAI"""
    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.models.list()
        return True
    except Exception as e:
        error_message = str(e)
        if "insufficient_quota" in error_message or "429" in error_message:
            logger.error("Ошибка API OpenAI: Недостаточно квоты или превышен лимит запросов.")
        else:
            logger.error(f"Ошибка API OpenAI: {error_message}")
        return False

def split_text(text, max_chunk_size):
    """Разделить длинный текст на части подходящего размера"""
    words = text.split()
    chunks = []
    current_chunk = []
    current_size = 0
    
    for word in words:
        word_size = len(word) + 1  # +1 для пробела
        if current_size + word_size > max_chunk_size and current_chunk:
            chunks.append(' '.join(current_chunk))
            current_chunk = [word]
            current_size = word_size
        else:
            current_chunk.append(word)
            current_size += word_size
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks

def extract_json_from_text(text):
    """Извлечь JSON массив из текстового ответа"""
    try:
        # Ищем JSON в ответе с помощью регулярного выражения
        json_match = re.search(r'(\[.*\])', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            return json.loads(json_str)
        
        # Если не нашли с помощью regex, пробуем парсить весь ответ
        if text.strip().startswith('[') and text.strip().endswith(']'):
            return json.loads(text.strip())
        
        return []
    except Exception as e:
        logger.error(f"Не удалось извлечь JSON из ответа: {str(e)}")
        return []

def get_main_host_name(alias):
    """Определяет основное имя ведущего по его алиасу"""
    from modules.utils.config import HOST_ALIASES
    
    # Приводим к нижнему регистру для удобства сравнения
    alias_lower = alias.lower()
    
    for host, aliases in HOST_ALIASES.items():
        if host.lower() == alias_lower:
            return host
        for host_alias in aliases:
            if host_alias.lower() == alias_lower:
                return host
    
    # Если алиас не найден, возвращаем исходное значение
    return alias

def format_time(seconds):
    """Форматирует время в секундах в формат HH:MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" 