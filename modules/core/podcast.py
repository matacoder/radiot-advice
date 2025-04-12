"""
Модуль для скачивания подкаста Радио-Т, его транскрибирования
и извлечения информации о продуктах и технологиях.
"""

import os
import sys
import json
import time
import sqlite3
import requests
import xml.etree.ElementTree as ET
import re
import subprocess
from datetime import datetime
from pathlib import Path
import logging
import threading

try:
    import openai
    import whisper
    import torch
except ImportError:
    print("Для работы скрипта требуются библиотеки openai и whisper.")
    print("Установите их: pip install openai git+https://github.com/openai/whisper.git torch")
    sys.exit(1)

from modules.utils.config import (
    DOWNLOAD_DIR, TRANSCRIPT_DIR, RECOMMENDATIONS_DIR, DB_PATH,
    HOSTS, HOST_ALIASES, WHISPER_MODEL, RSS_URL
)
from modules.utils.helpers import load_api_key, check_openai_api_key, split_text, extract_json_from_text
from modules.utils.database import init_db, save_episode_to_db, update_episode_status, get_all_episodes

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Проверка наличия FFmpeg
def check_ffmpeg():
    """Проверяет, установлен ли FFmpeg, и выводит соответствующее сообщение"""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        print("ОШИБКА: FFmpeg не установлен или не найден в PATH.")
        print("FFmpeg требуется для обработки аудио файлов.")
        print("Инструкции по установке:")
        print("  - Windows: https://www.gyan.dev/ffmpeg/builds/ или через chocolatey: choco install ffmpeg")
        print("  - macOS: brew install ffmpeg")
        print("  - Linux: sudo apt install ffmpeg или эквивалент для вашего дистрибутива")
        return False

# Загрузка RSS и получение последнего эпизода
def get_latest_episode():
    """Получить информацию о последнем эпизоде подкаста"""
    logger.info("Загрузка RSS-ленты...")
    response = requests.get(RSS_URL)
    
    if response.status_code != 200:
        logger.error(f"Ошибка загрузки RSS: {response.status_code}")
        return None
    
    # Парсинг XML
    root = ET.fromstring(response.content)
    
    # Пространство имен RSS
    ns = {'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'}
    
    # Находим первый (самый новый) эпизод
    item = root.find(".//item")
    if item is None:
        logger.error("Не удалось найти эпизоды в RSS")
        return None
    
    # Извлекаем данные
    title = item.find("title").text
    published_date = item.find("pubDate").text
    
    # Ищем URL аудиофайла
    enclosure = item.find("enclosure")
    if enclosure is None:
        logger.error("Не удалось найти ссылку на аудиофайл")
        return None
    audio_url = enclosure.get("url")
    
    # Ищем номер эпизода в заголовке
    episode_number = None
    for part in title.split():
        if part.isdigit():
            episode_number = int(part)
            break
    
    if not episode_number:
        logger.error("Не удалось определить номер эпизода")
        return None
    
    # Преобразуем дату в более удобный формат
    try:
        dt = datetime.strptime(published_date, "%a, %d %b %Y %H:%M:%S %z")
        published_date_formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        published_date_formatted = published_date
    
    episode = {
        "episode_number": episode_number,
        "title": title,
        "published_date": published_date_formatted,
        "audio_url": audio_url
    }
    
    return episode

# Получение списка всех эпизодов из RSS-ленты
def get_all_episodes_from_rss(limit=10):
    """Получить информацию о последних эпизодах подкаста из RSS"""
    logger.info("Загрузка RSS-ленты для получения списка эпизодов...")
    response = requests.get(RSS_URL)
    
    if response.status_code != 200:
        logger.error(f"Ошибка загрузки RSS: {response.status_code}")
        return []
    
    # Парсинг XML
    root = ET.fromstring(response.content)
    
    # Находим все эпизоды
    items = root.findall(".//item")
    if not items:
        logger.error("Не удалось найти эпизоды в RSS")
        return []
    
    episodes = []
    for item in items[:limit]:  # Ограничиваем количество эпизодов
        # Извлекаем данные
        title = item.find("title").text
        published_date = item.find("pubDate").text
        
        # Ищем URL аудиофайла
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        audio_url = enclosure.get("url")
        
        # Ищем номер эпизода в заголовке
        episode_number = None
        for part in title.split():
            if part.isdigit():
                episode_number = int(part)
                break
        
        if not episode_number:
            continue
        
        # Преобразуем дату в более удобный формат
        try:
            dt = datetime.strptime(published_date, "%a, %d %b %Y %H:%M:%S %z")
            published_date_formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            published_date_formatted = published_date
        
        episodes.append({
            "episode_number": episode_number,
            "title": title,
            "published_date": published_date_formatted,
            "audio_url": audio_url
        })
    
    return episodes

# Скачивание аудиофайла
def download_episode(episode_number, audio_url):
    """Скачать аудиофайл эпизода"""
    file_path = os.path.join(DOWNLOAD_DIR, f"episode_{episode_number}.mp3")
    
    # Проверяем, существует ли файл уже
    if os.path.exists(file_path):
        logger.info(f"Эпизод {episode_number} уже скачан")
        return file_path
    
    logger.info(f"Скачивание эпизода {episode_number}...")
    response = requests.get(audio_url, stream=True)
    
    if response.status_code != 200:
        logger.error(f"Ошибка скачивания: {response.status_code}")
        return None
    
    # Получаем размер файла для отображения прогресса
    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024  # 1 Kb
    
    # Скачиваем с отображением прогресса
    with open(file_path, 'wb') as f:
        downloaded = 0
        for data in response.iter_content(block_size):
            f.write(data)
            downloaded += len(data)
            if total_size > 0:
                progress = int(50 * downloaded / total_size)
                sys.stdout.write(f"\r[{'=' * progress}{' ' * (50-progress)}] {downloaded / 1024 / 1024:.1f}MB / {total_size / 1024 / 1024:.1f}MB")
                sys.stdout.flush()
    
    sys.stdout.write("\n")
    logger.info(f"Эпизод {episode_number} скачан: {file_path}")
    return file_path

# Транскрибирование аудио
def transcribe_audio(audio_path, model_name=WHISPER_MODEL, language="ru", initial_prompt=None, 
                    temperature=0.0, beam_size=5, condition_on_previous_text=True, verbose=False, 
                    debug_output=False, use_diarization=True):
    """
    Транскрибирует аудио файл с помощью локальной модели OpenAI Whisper.
    При включенной диаризации также определяет говорящих.
    
    Parameters:
        audio_path (str): Путь к аудио файлу
        model_name (str): Название модели Whisper (tiny, base, small, medium, large)
        language (str): Язык аудио (например, "ru" для русского)
        initial_prompt (str): Начальный текст, помогающий модели понять контекст
        temperature (float): Параметр температуры для генерации текста (0.0 = детерминированный)
        beam_size (int): Размер луча для beam search
        condition_on_previous_text (bool): Учитывать ли предыдущий текст при генерации
        verbose (bool): Подробный вывод
        debug_output (bool): Вывод отладочной информации
        use_diarization (bool): Использовать диаризацию для определения говорящих
    
    Returns:
        str: Полный транскрибированный текст или None в случае ошибки
    """
    start_time = time.time()
    
    # Логируем начало процесса
    logger.info(f"Загрузка модели Whisper {model_name}...")
    
    try:
        # Проверяем существование файла
        if not os.path.exists(audio_path):
            logger.error(f"Файл не найден: {audio_path}")
            return None
            
        # Проверка доступности CUDA
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Используется устройство: {device}")
        
        # Загрузка модели
        model = whisper.load_model(model_name, device=device)
        
        logger.info(f"Начало транскрибирования файла {audio_path}...")
        logger.info("Этот процесс может занять длительное время в зависимости от размера файла")
        
        # Сохраняем время начала для отслеживания прогресса
        start_processing_time = time.time()
        
        # Функция для обновления статуса
        def status_update():
            while True:
                elapsed = time.time() - start_processing_time
                logger.info(f"ПРОГРЕСС: Транскрибирование продолжается... Прошло времени: {int(elapsed)} сек.")
                
                # Запись в файл для проверки прогресса извне
                with open("transcribe_progress.txt", "a") as f:
                    f.write(f"{datetime.now().isoformat()} - Длительность: {int(elapsed)} сек.\n")
                    
                time.sleep(30)  # Обновление каждые 30 секунд
        
        # Запускаем поток обновления статуса
        status_thread = threading.Thread(target=status_update)
        status_thread.daemon = True
        status_thread.start()
        
        # Подготовка опций транскрибирования
        transcribe_options = {
            "language": language,
            "temperature": temperature,
            "verbose": True  # Всегда включаем подробный вывод
        }
        
        # Добавление начального текста, если он указан
        if initial_prompt:
            transcribe_options["initial_prompt"] = initial_prompt
        
        logger.info("Запуск процесса транскрибирования...")
        
        # Выполнение транскрибирования
        result = model.transcribe(audio_path, **transcribe_options)
        
        # Если используем диаризацию, обрабатываем результат с определением говорящих
        if use_diarization:
            try:
                from modules.utils.diarization import SpeakerDiarization
                
                logger.info("Запуск процесса диаризации для определения говорящих...")
                
                # Создаем экземпляр класса для диаризации
                diarization = SpeakerDiarization(num_speakers=len(HOSTS))
                
                # Получаем сегменты с определением говорящих
                speaker_segments = diarization.process_audio(audio_path)
                
                if speaker_segments:
                    logger.info(f"Диаризация успешно выполнена, найдено {len(speaker_segments)} сегментов")
                    
                    # Комбинируем результаты транскрипции с диаризацией
                    combined_segments = diarization.combine_with_transcript(
                        speaker_segments,
                        result.get("segments", [])
                    )
                    
                    # Форматируем текст с указанием говорящих
                    transcript = diarization.format_transcript_with_speakers(combined_segments)
                    
                    # Сохраняем оригинальные сегменты в результат для отладки
                    if debug_output:
                        result["speaker_segments"] = speaker_segments
                        result["combined_segments"] = combined_segments
                else:
                    logger.warning("Диаризация не выполнена, используется обычная транскрипция")
                    transcript = result["text"]
            except Exception as e:
                logger.error(f"Ошибка при выполнении диаризации: {str(e)}")
                logger.warning("Используется обычная транскрипция без диаризации")
                transcript = result["text"]
        else:
            # Получение текста из результата без диаризации
            transcript = result["text"]
        
        elapsed_time = time.time() - start_time
        logger.info(f"Транскрибирование ЗАВЕРШЕНО за {elapsed_time:.2f} секунд")
        logger.info(f"Получено {len(transcript)} символов текста")
        
        if debug_output and transcript:
            debug_file = f"{Path(audio_path).stem}_debug.json"
            with open(debug_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"Отладочные данные сохранены в {debug_file}")
        
        return transcript
    
    except Exception as e:
        logger.error(f"Ошибка при транскрибировании: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

# Сохранение транскрипции
def save_transcript(episode_number, transcript_text, model_name=WHISPER_MODEL):
    """Сохранить транскрипцию в файл"""
    file_path = os.path.join(TRANSCRIPT_DIR, f"episode_{episode_number}_transcript.txt")
    model_info_path = os.path.join(TRANSCRIPT_DIR, f"episode_{episode_number}_model_info.json")
    
    # Сохраняем текст транскрипции
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(transcript_text)
    
    # Сохраняем информацию о модели
    model_info = {
        "model": model_name,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(model_info_path, "w", encoding="utf-8") as f:
        json.dump(model_info, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Транскрипция сохранена: {file_path}")
    logger.info(f"Информация о модели сохранена: {model_info_path}")
    return file_path

# Проверка необходимости обновления транскрипции
def should_update_transcript(episode_number, current_model=WHISPER_MODEL, force_update=False):
    """Проверяет, нужно ли обновлять транскрипцию из-за смены модели"""
    # Если установлен флаг принудительного обновления, всегда обновляем
    if force_update:
        logger.info(f"Принудительное обновление транскрипции для эпизода #{episode_number}")
        return True
    
    model_info_path = os.path.join(TRANSCRIPT_DIR, f"episode_{episode_number}_model_info.json")
    
    # Если информации о модели нет, нужно обновлять
    if not os.path.exists(transcript_path := os.path.join(TRANSCRIPT_DIR, f"episode_{episode_number}_transcript.txt")):
        return True
    
    if not os.path.exists(model_info_path):
        return True
    
    try:
        with open(model_info_path, "r", encoding="utf-8") as f:
            model_info = json.load(f)
        
        # Если модель изменилась, нужно обновлять
        if model_info.get("model") != current_model:
            logger.info(f"Обнаружена новая модель: {current_model}, предыдущая: {model_info.get('model')}")
            return True
    except Exception as e:
        logger.error(f"Ошибка при чтении информации о модели: {str(e)}")
        return True
    
    return False

# Извлечение рекомендаций из транскрипции
def extract_recommendations(transcript_text, episode_number, api_key):
    """Извлечение рекомендаций из транскрипции используя OpenAI API"""
    client = openai.OpenAI(api_key=api_key)
    
    logger.info("Анализ транскрипции для извлечения рекомендаций...")
    
    hosts_list = ", ".join(HOSTS)
    
    # Создаем строку всех возможных алиасов для ведущих
    aliases_text = "Возможные способы обращения к ведущим:\n"
    for host, aliases in HOST_ALIASES.items():
        aliases_text += f"{host}: {', '.join(aliases)}\n"
    
    # Создаем промпт для модели
    system_prompt = f"""
    🎯 Цель:
    Изучи транскрипцию подкаста "Радио-Т" и составь список всех упомянутых программ, продуктов, технологий или языков программирования.
    
    Для контекста: Ведущие подкаста: {hosts_list}.
    {aliases_text}
    
    📝 Формат ответа:
    [
        {{
            "name": "Название продукта (кратко, без версий)",
            "description": "2–3 строки, простым языком, что это такое",
            "hosts_opinion": "понравилось или нет, цитата или передача тона",
            "ai_comment": "одно предложение — нейтральное, но с характером",
            "website": "официальный сайт, если можно найти",
            "mentioned_by": "кто из ведущих упомянул (или 'unknown')",
            "timestamp": "временная метка в формате HH:MM:SS или пусто, если не указана",
            "confidence": число от 1 до 100, показывающее уверенность в точности информации
        }}
    ]
    
    🎨 Стиль:
    Пиши живо, но аккуратно — как если бы готовил карточки для Telegram-канала с айтишной аудиторией. 
    Можно добавлять немного иронии, если это уместно.
    
    Если продуктов нет, верни пустой массив.
    """
    
    try:
        # Для длинных транскрипций разбиваем текст на части
        max_chunk_size = 15000
        chunks = split_text(transcript_text, max_chunk_size)
        
        all_recommendations = []
        
        for i, chunk in enumerate(chunks):
            logger.info(f"Обработка части {i+1}/{len(chunks)} транскрипции...")
            
            try:
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",  # Используем доступную модель
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Вот фрагмент транскрипции эпизода {episode_number} подкаста 'Радио-Т'. Найди в нем все упомянутые программы, продукты и технологии:\n\n{chunk}"}
                    ],
                    temperature=0.3,
                    max_tokens=2000
                )
                
                result_text = response.choices[0].message.content
                
                # Попытка извлечь JSON из ответа
                recommendations = extract_json_from_text(result_text)
                
                if recommendations:
                    all_recommendations.extend(recommendations)
                
            except Exception as chunk_error:
                logger.error(f"Ошибка при обработке части {i+1}: {str(chunk_error)}")
                continue
            
            # Пауза, чтобы не превышать лимиты API
            time.sleep(1)
        
        # Сохраняем рекомендации в JSON файл
        save_recommendations_to_json(all_recommendations, episode_number)
        
        return all_recommendations
        
    except Exception as e:
        logger.error(f"Ошибка извлечения рекомендаций: {str(e)}")
        return []

# Сохранение рекомендаций в JSON файл
def save_recommendations_to_json(recommendations, episode_number):
    """Сохранить информацию о продуктах/технологиях в JSON файл"""
    if not recommendations:
        logger.info("Нет продуктов/технологий для сохранения в JSON")
        return
    
    file_path = os.path.join(RECOMMENDATIONS_DIR, f"episode_{episode_number}_products.json")
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(recommendations, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Информация о продуктах/технологиях сохранена в {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении продуктов/технологий в JSON: {str(e)}")

# Загрузка рекомендаций из JSON файла
def load_recommendations_from_json(episode_number):
    """Загрузить информацию о продуктах/технологиях из существующего JSON файла"""
    # Проверяем новый формат файла
    file_path = os.path.join(RECOMMENDATIONS_DIR, f"episode_{episode_number}_products.json")
    if not os.path.exists(file_path):
        # Проверяем старый формат файла
        file_path = os.path.join(RECOMMENDATIONS_DIR, f"episode_{episode_number}_recommendations.json")
        if not os.path.exists(file_path):
            logger.info(f"Файл с продуктами/технологиями не найден: {file_path}")
            return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            recommendations = json.load(f)
        
        logger.info(f"Загружены данные из файла: {file_path} (найдено {len(recommendations)} продуктов/технологий)")
        return recommendations
    except Exception as e:
        logger.error(f"Ошибка при загрузке продуктов/технологий из файла: {str(e)}")
        return None

# Получение статуса эпизода
def get_episode_status(episode_number):
    """
    Получает статус обработки эпизода
    
    Returns:
        dict: Словарь с информацией о статусе эпизода
        {
            'exists': bool,  # Существует ли эпизод в базе
            'downloaded': bool,  # Скачан ли аудиофайл
            'transcribed': bool,  # Есть ли транскрипция
            'recommendations': bool,  # Есть ли извлеченные рекомендации
            'processed': int,  # Статус обработки из БД (0-2)
        }
    """
    status = {
        'exists': False,
        'downloaded': False,
        'transcribed': False,
        'recommendations': False,
        'processed': 0
    }
    
    # Проверяем наличие в базе данных
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, processed FROM episodes WHERE episode_number = ?", (episode_number,))
    result = cursor.fetchone()
    
    if result:
        status['exists'] = True
        status['processed'] = result[1]
    
    conn.close()
    
    # Проверяем наличие файлов
    audio_path = os.path.join(DOWNLOAD_DIR, f"episode_{episode_number}.mp3")
    transcript_path = os.path.join(TRANSCRIPT_DIR, f"episode_{episode_number}_transcript.txt")
    recommendation_path = os.path.join(RECOMMENDATIONS_DIR, f"episode_{episode_number}_products.json")
    
    status['downloaded'] = os.path.exists(audio_path)
    status['transcribed'] = os.path.exists(transcript_path)
    status['recommendations'] = os.path.exists(recommendation_path)
    
    return status

# Обработка эпизода целиком
def process_episode(episode_number, force_retranscribe=False):
    """
    Полная обработка эпизода: скачивание, транскрибирование и извлечение рекомендаций
    
    Returns:
        bool: Успешно ли выполнена обработка
    """
    # Проверяем существование эпизода
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, audio_url FROM episodes WHERE episode_number = ?", (episode_number,))
    result = cursor.fetchone()
    
    if result:
        episode_id, audio_url = result
        logger.info(f"Найден эпизод #{episode_number} в базе данных (ID: {episode_id})")
    else:
        # Получаем информацию из RSS
        episodes = get_all_episodes_from_rss(50)  # Получаем большой список для поиска
        episode_data = None
        
        for ep in episodes:
            if ep["episode_number"] == episode_number:
                episode_data = ep
                break
        
        if not episode_data:
            logger.error(f"Эпизод #{episode_number} не найден ни в базе данных, ни в RSS.")
            conn.close()
            return False
        
        # Сохраняем информацию в базу
        episode_id = save_episode_to_db(episode_data)
        audio_url = episode_data["audio_url"]
        logger.info(f"Эпизод #{episode_number} добавлен в базу данных (ID: {episode_id})")
    
    # Скачивание аудио
    audio_path = download_episode(episode_number, audio_url)
    if not audio_path:
        logger.error(f"Не удалось скачать эпизод #{episode_number}")
        conn.close()
        return False
    
    # Транскрибирование
    transcript_path = os.path.join(TRANSCRIPT_DIR, f"episode_{episode_number}_transcript.txt")
    
    # Проверяем необходимость обновления транскрипции
    need_update = should_update_transcript(episode_number, force_update=force_retranscribe)
    
    if os.path.exists(transcript_path) and not need_update:
        logger.info(f"Найдена существующая транскрипция: {transcript_path}")
        with open(transcript_path, 'r', encoding='utf-8') as f:
            transcript = f.read()
        logger.info(f"Загружена существующая транскрипция (длина: {len(transcript)} символов)")
    else:
        if need_update and os.path.exists(transcript_path):
            logger.info(f"Обнаружена смена модели или флаг принудительного обновления. Запускаем новую транскрипцию...")
        
        # Транскрибирование аудио с использованием локальной модели Whisper
        transcript = transcribe_audio(
            audio_path, 
            model_name=WHISPER_MODEL,
            language="ru",
            initial_prompt=f"Подкаст Радио-Т с ведущими {', '.join(HOSTS)}",
            temperature=0.0,
            beam_size=5,
            condition_on_previous_text=True,
            verbose=True,
            debug_output=True,
            use_diarization=True
        )
        
        if not transcript:
            logger.error(f"Не удалось транскрибировать эпизод #{episode_number}")
            conn.close()
            return False
        
        # Сохранение транскрипции
        save_transcript(episode_number, transcript, WHISPER_MODEL)
    
    # Обновление статуса эпизода: транскрибирован
    update_episode_status(episode_id, 1)
    
    # Загрузка API ключа для анализа текста
    api_key = load_api_key()
    if not api_key:
        logger.error("API ключ OpenAI не найден. Невозможно извлечь рекомендации.")
        conn.close()
        return False
    
    # Проверка работоспособности API ключа
    if not check_openai_api_key(api_key):
        logger.error("API ключ OpenAI не работает. Проверьте квоту и лимиты.")
        conn.close()
        return False
    
    # Извлечение рекомендаций
    recommendations = extract_recommendations(transcript, episode_number, api_key)
    
    if not recommendations:
        logger.error(f"Не удалось извлечь рекомендации для эпизода #{episode_number}")
        conn.close()
        return False
    
    # Сохранение рекомендаций в БД
    from modules.utils.database import save_recommendations_to_db
    rec_count = save_recommendations_to_db(recommendations, episode_id)
    
    # Обновление статуса эпизода: полностью обработан
    update_episode_status(episode_id, 2)
    
    logger.info(f"Обработка эпизода #{episode_number} успешно завершена")
    logger.info(f"Извлечено {rec_count} рекомендаций")
    
    conn.close()
    return True 