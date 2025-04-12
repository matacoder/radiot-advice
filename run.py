#!/usr/bin/env python3
"""
Радио-Т Транскрибер - сервис для скачивания, транскрибирования и анализа подкаста Радио-Т.
"""

import os
import sys
import argparse
import logging

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    """Точка входа в приложение"""
    # Создаем парсер аргументов командной строки
    parser = argparse.ArgumentParser(description="Радио-Т Транскрибер")
    parser.add_argument("--web", action="store_true", help="Запустить веб-интерфейс")
    parser.add_argument("--console", action="store_true", help="Запустить консольный интерфейс")
    parser.add_argument("--process", type=int, help="Обработать эпизод с указанным номером")
    parser.add_argument("--force-retranscribe", action="store_true", help="Принудительно повторно транскрибировать аудио")
    
    args = parser.parse_args()
    
    # Проверяем наличие зависимостей
    try:
        import openai
        import whisper
        import torch
    except ImportError:
        logger.error("Отсутствуют необходимые зависимости.")
        logger.error("Установите их: pip install openai git+https://github.com/openai/whisper.git torch")
        return
    
    # Если не указаны аргументы, запускаем консольный интерфейс по умолчанию
    if not (args.web or args.console or args.process):
        args.console = True
    
    # Запуск веб-интерфейса
    if args.web:
        try:
            from modules.api.server import start_server
            logger.info("Запуск веб-интерфейса...")
            start_server()
        except ImportError as e:
            logger.error("Не удалось запустить веб-интерфейс.")
            logger.error(f"Ошибка: {str(e)}")
            logger.error("Установите необходимые зависимости: pip install fastapi uvicorn jinja2")
            import traceback
            logger.error(traceback.format_exc())
    
    # Запуск консольного интерфейса
    elif args.console:
        try:
            from modules.console.cli import run_cli
            logger.info("Запуск консольного интерфейса...")
            run_cli()
        except ImportError:
            logger.error("Не удалось запустить консольный интерфейс.")
    
    # Обработка конкретного эпизода
    elif args.process:
        from modules.core.podcast import process_episode
        from modules.utils.database import init_db
        
        # Инициализация базы данных
        init_db()
        
        logger.info(f"Запуск обработки эпизода #{args.process}...")
        result = process_episode(args.process, args.force_retranscribe)
        
        if result:
            logger.info(f"Эпизод #{args.process} успешно обработан!")
        else:
            logger.error(f"При обработке эпизода #{args.process} возникли ошибки.")

if __name__ == "__main__":
    main() 