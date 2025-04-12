"""
Консольный интерфейс для управления процессом транскрибирования
"""

import os
import sys
import logging
from modules.core.podcast import (
    get_latest_episode, get_all_episodes_from_rss, 
    get_episode_status, process_episode
)
from modules.utils.database import (
    init_db, get_all_episodes, get_episode_recommendations,
    search_recommendations
)

logger = logging.getLogger(__name__)

def print_header():
    """Вывод заголовка программы"""
    print("\n" + "=" * 60)
    print("  Транскрибер подкаста Радио-Т с анализом рекомендаций  ")
    print("=" * 60)

def print_menu():
    """Вывод главного меню"""
    print("\nГЛАВНОЕ МЕНЮ:")
    print("1. Проверить наличие новых эпизодов")
    print("2. Выбрать эпизод для обработки")
    print("3. Просмотреть информацию об эпизоде")
    print("4. Поиск по рекомендациям")
    print("5. Запустить веб-интерфейс")
    print("0. Выход")

def check_new_episodes():
    """Проверка наличия новых эпизодов"""
    print("\nПроверка наличия новых эпизодов...")
    latest_episode = get_latest_episode()
    
    if not latest_episode:
        print("Не удалось получить информацию о последнем эпизоде.")
        return
    
    print(f"Найден последний эпизод: #{latest_episode['episode_number']} - {latest_episode['title']}")
    
    status = get_episode_status(latest_episode['episode_number'])
    
    if status['exists']:
        print("Этот эпизод уже есть в базе данных.")
        
        if status['transcribed']:
            print("У эпизода уже есть транскрипция.")
        else:
            print("Транскрипция для эпизода отсутствует.")
            
        if status['recommendations']:
            print("Рекомендации для эпизода уже извлечены.")
        else:
            print("Рекомендации для эпизода отсутствуют.")
        
        print(f"Статус обработки: {status['processed']}")
        
        if status['processed'] < 2:
            choice = input("\nХотите продолжить обработку эпизода? (y/n): ")
            if choice.lower() == 'y':
                process_episode_with_progress(latest_episode['episode_number'])
    else:
        print("Этот эпизод еще не добавлен в базу данных.")
        choice = input("\nХотите скачать и обработать этот эпизод? (y/n): ")
        
        if choice.lower() == 'y':
            process_episode_with_progress(latest_episode['episode_number'])

def select_episode_for_processing():
    """Выбор эпизода для обработки"""
    print("\nПолучение списка эпизодов из RSS-ленты...")
    rss_episodes = get_all_episodes_from_rss(20)  # Получаем 20 последних эпизодов
    
    if not rss_episodes:
        print("Не удалось получить список эпизодов из RSS.")
        return
    
    print("\nПоследние эпизоды из RSS:")
    for i, ep in enumerate(rss_episodes[:10], 1):  # Показываем только 10 эпизодов
        print(f"{i}. #{ep['episode_number']} - {ep['title']}")
    
    print("\nЭпизоды в базе данных:")
    db_episodes = get_all_episodes()
    for i, ep in enumerate(db_episodes[:10], 1):  # Показываем только 10 эпизодов
        status_text = "Не обработан"
        if ep['processed'] == 1:
            status_text = "Транскрибирован"
        elif ep['processed'] == 2:
            status_text = "Полностью обработан"
        
        print(f"{i}. #{ep['episode_number']} - {ep['title']} ({status_text})")
    
    while True:
        try:
            choice = input("\nВведите номер эпизода для обработки (или 0 для возврата): ")
            
            if choice == '0':
                return
                
            episode_number = int(choice)
            
            # Проверяем статус эпизода
            status = get_episode_status(episode_number)
            
            if status['exists']:
                print(f"\nЭпизод #{episode_number} найден в базе данных.")
                print(f"Статус: {'Скачан' if status['downloaded'] else 'Не скачан'}, "
                      f"{'Транскрибирован' if status['transcribed'] else 'Не транскрибирован'}, "
                      f"{'Рекомендации извлечены' if status['recommendations'] else 'Рекомендации не извлечены'}")
                
                force_retranscribe = False
                if status['transcribed']:
                    retranscribe = input("Хотите повторно транскрибировать эпизод? (y/n): ")
                    force_retranscribe = retranscribe.lower() == 'y'
                
                process_episode_with_progress(episode_number, force_retranscribe)
                break
            else:
                # Проверяем, есть ли такой эпизод в RSS
                episode_in_rss = False
                for ep in rss_episodes:
                    if ep['episode_number'] == episode_number:
                        episode_in_rss = True
                        break
                
                if episode_in_rss:
                    print(f"\nЭпизод #{episode_number} найден в RSS, но отсутствует в базе данных.")
                    proceed = input("Хотите скачать и обработать этот эпизод? (y/n): ")
                    
                    if proceed.lower() == 'y':
                        process_episode_with_progress(episode_number)
                        break
                else:
                    print(f"Эпизод #{episode_number} не найден ни в базе данных, ни в RSS.")
                    continue
                    
        except ValueError:
            print("Введите корректный номер эпизода.")

def process_episode_with_progress(episode_number, force_retranscribe=False):
    """Обработка эпизода с выводом прогресса"""
    print(f"\nНачало обработки эпизода #{episode_number}")
    
    if force_retranscribe:
        print("(Выбрано принудительное обновление транскрипции)")
    
    result = process_episode(episode_number, force_retranscribe)
    
    if result:
        print(f"\nЭпизод #{episode_number} успешно обработан!")
    else:
        print(f"\nПри обработке эпизода #{episode_number} возникли ошибки.")

def view_episode_info():
    """Просмотр информации об эпизоде"""
    print("\nСписок доступных эпизодов:")
    episodes = get_all_episodes()
    
    if not episodes:
        print("В базе данных нет эпизодов.")
        return
    
    for i, ep in enumerate(episodes[:15], 1):  # Показываем только 15 эпизодов
        status_text = "Не обработан"
        if ep['processed'] == 1:
            status_text = "Транскрибирован"
        elif ep['processed'] == 2:
            status_text = "Полностью обработан"
        
        print(f"{i}. #{ep['episode_number']} - {ep['title']} ({status_text})")
    
    while True:
        try:
            choice = input("\nВведите номер эпизода для просмотра (или 0 для возврата): ")
            
            if choice == '0':
                return
                
            episode_number = int(choice)
            
            # Ищем эпизод в списке
            selected_episode = None
            for ep in episodes:
                if ep['episode_number'] == episode_number:
                    selected_episode = ep
                    break
            
            if not selected_episode:
                print(f"Эпизод #{episode_number} не найден в базе данных.")
                continue
                
            print(f"\nИнформация об эпизоде #{selected_episode['episode_number']}:")
            print(f"Название: {selected_episode['title']}")
            print(f"Дата публикации: {selected_episode['published_date']}")
            
            status = get_episode_status(episode_number)
            print(f"Скачан: {'Да' if status['downloaded'] else 'Нет'}")
            print(f"Транскрибирован: {'Да' if status['transcribed'] else 'Нет'}")
            print(f"Рекомендации извлечены: {'Да' if status['recommendations'] else 'Нет'}")
            
            # Если есть рекомендации, предлагаем их просмотреть
            if status['recommendations']:
                view_recs = input("\nХотите просмотреть рекомендации этого эпизода? (y/n): ")
                
                if view_recs.lower() == 'y':
                    recommendations = get_episode_recommendations(selected_episode['id'])
                    
                    if not recommendations:
                        print("Рекомендации не найдены, хотя файл существует.")
                        break
                        
                    print(f"\nРекомендации в эпизоде #{episode_number} ({len(recommendations)}):")
                    
                    for i, rec in enumerate(recommendations, 1):
                        print(f"\n{i}. {rec['name']}")
                        print(f"   Описание: {rec['description']}")
                        
                        if rec['hosts_opinion']:
                            print(f"   Мнение ведущих: {rec['hosts_opinion']}")
                            
                        if rec['mentioned_by'] and rec['mentioned_by'].lower() != 'unknown':
                            print(f"   Упомянул: {rec['mentioned_by']}")
                        
                        # Прерываем вывод, если рекомендаций слишком много
                        if i % 5 == 0 and i < len(recommendations):
                            more = input("\nПоказать еще? (y/n): ")
                            if more.lower() != 'y':
                                break
            
            break
                
        except ValueError:
            print("Введите корректный номер эпизода.")

def search_in_recommendations():
    """Поиск по рекомендациям"""
    search_query = input("\nВведите поисковый запрос: ")
    
    if not search_query:
        print("Запрос не может быть пустым.")
        return
        
    print(f"\nПоиск по запросу: '{search_query}'")
    results = search_recommendations(search_query)
    
    if not results:
        print("По вашему запросу ничего не найдено.")
        return
        
    print(f"\nНайдено {len(results)} результатов:")
    
    for i, rec in enumerate(results, 1):
        print(f"\n{i}. {rec['name']} (Эпизод #{rec['episode_number']})")
        print(f"   Описание: {rec['description']}")
        
        if rec['hosts_opinion']:
            print(f"   Мнение ведущих: {rec['hosts_opinion']}")
            
        if rec['mentioned_by'] and rec['mentioned_by'].lower() != 'unknown':
            print(f"   Упомянул: {rec['mentioned_by']}")
        
        # Прерываем вывод, если результатов слишком много
        if i % 5 == 0 and i < len(results):
            more = input("\nПоказать еще? (y/n): ")
            if more.lower() != 'y':
                break

def start_web_interface():
    """Запуск веб-интерфейса"""
    print("\nЗапуск веб-интерфейса...")
    
    try:
        from modules.api.server import start_server
        start_server()
    except ImportError as e:
        print("Не удалось запустить веб-интерфейс. Проверьте наличие модуля FastAPI.")
        print("Ошибка:", str(e))
        print("Установите необходимые зависимости: pip install fastapi uvicorn jinja2")
        print("\nВозвращаемся в консольный режим...")
        return

def run_cli():
    """Запуск консольного интерфейса"""
    # Инициализация базы данных
    init_db()
    
    print_header()
    
    while True:
        print_menu()
        choice = input("\nВыберите действие: ")
        
        if choice == '0':
            print("\nЗавершение работы программы...")
            break
        elif choice == '1':
            check_new_episodes()
        elif choice == '2':
            select_episode_for_processing()
        elif choice == '3':
            view_episode_info()
        elif choice == '4':
            search_in_recommendations()
        elif choice == '5':
            start_web_interface()
        else:
            print("Некорректный выбор. Пожалуйста, выберите действие из меню.")

if __name__ == "__main__":
    run_cli() 