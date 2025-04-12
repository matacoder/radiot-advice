"""
Функции для работы с базой данных
"""

import sqlite3
import logging
from modules.utils.config import DB_PATH
from modules.utils.helpers import get_main_host_name

logger = logging.getLogger(__name__)

def init_db():
    """Создание необходимых таблиц в базе данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица эпизодов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_number INTEGER UNIQUE,
        title TEXT,
        published_date TEXT,
        audio_url TEXT,
        processed INTEGER DEFAULT 0
    )
    ''')
    
    # Таблица продуктов/технологий
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id INTEGER,
        from_host TEXT,
        to_host TEXT,
        product_name TEXT,
        description TEXT,
        timestamp TEXT,
        confidence INTEGER,
        hosts_opinion TEXT,
        ai_comment TEXT,
        website TEXT,
        mentioned_by TEXT,
        FOREIGN KEY(episode_id) REFERENCES episodes(id)
    )
    ''')
    
    conn.commit()
    conn.close()
    
    logger.info("База данных инициализирована")

def save_episode_to_db(episode):
    """Сохранить информацию об эпизоде в базу данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Проверяем, существует ли уже эпизод
    cursor.execute("SELECT id FROM episodes WHERE episode_number = ?", (episode["episode_number"],))
    result = cursor.fetchone()
    
    if result:
        episode_id = result[0]
        logger.info(f"Эпизод {episode['episode_number']} уже существует в базе данных")
    else:
        # Добавляем новый эпизод
        cursor.execute("""
        INSERT INTO episodes (episode_number, title, published_date, audio_url, processed)
        VALUES (?, ?, ?, ?, 0)
        """, (episode["episode_number"], episode["title"], episode["published_date"], episode["audio_url"]))
        conn.commit()
        episode_id = cursor.lastrowid
        logger.info(f"Эпизод {episode['episode_number']} добавлен в базу данных")
    
    conn.close()
    return episode_id

def update_episode_status(episode_id, status):
    """Обновить статус обработки эпизода"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("UPDATE episodes SET processed = ? WHERE id = ?", (status, episode_id))
    conn.commit()
    conn.close()
    
    logger.info(f"Статус эпизода (ID: {episode_id}) обновлен на {status}")

def save_recommendations_to_db(recommendations, episode_id):
    """Сохранить рекомендации в базу данных"""
    if not recommendations:
        logger.info("Нет продуктов/технологий для сохранения")
        return 0
    
    # Обновляем структуру базы данных, если нужно
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Проверяем наличие необходимых столбцов
    cursor.execute("PRAGMA table_info(recommendations)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Добавляем новые столбцы, если их нет
    if "hosts_opinion" not in columns:
        cursor.execute("ALTER TABLE recommendations ADD COLUMN hosts_opinion TEXT")
    if "ai_comment" not in columns:
        cursor.execute("ALTER TABLE recommendations ADD COLUMN ai_comment TEXT")
    if "website" not in columns:
        cursor.execute("ALTER TABLE recommendations ADD COLUMN website TEXT")
    if "mentioned_by" not in columns:
        cursor.execute("ALTER TABLE recommendations ADD COLUMN mentioned_by TEXT")
    
    conn.commit()
    
    saved_count = 0
    
    for rec in recommendations:
        # Проверяем обязательные поля
        if "name" not in rec:
            continue
        
        # Подготавливаем данные в соответствии со старым и новым форматом
        name = rec.get("name", rec.get("product_name", ""))
        description = rec.get("description", "")
        hosts_opinion = rec.get("hosts_opinion", "")
        ai_comment = rec.get("ai_comment", "")
        website = rec.get("website", "")
        mentioned_by = rec.get("mentioned_by", rec.get("from_host", "unknown"))
        to_host = rec.get("to_host", "unknown")  # для обратной совместимости
        timestamp = rec.get("timestamp", "")
        confidence = rec.get("confidence", 50)
        
        # Нормализуем имена ведущих (приводим алиасы к основным именам)
        mentioned_by_norm = get_main_host_name(mentioned_by)
        to_host_norm = get_main_host_name(to_host)
        
        # Вставляем запись
        cursor.execute("""
        INSERT INTO recommendations 
        (episode_id, from_host, to_host, product_name, description, timestamp, confidence, 
         hosts_opinion, ai_comment, website, mentioned_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode_id,
            mentioned_by_norm,  # используем как from_host для обратной совместимости
            to_host_norm,
            name,
            description,
            timestamp,
            confidence,
            hosts_opinion,
            ai_comment,
            website,
            mentioned_by_norm  # дублируем для нового поля
        ))
        saved_count += 1
    
    conn.commit()
    conn.close()
    
    logger.info(f"Сохранено {saved_count} продуктов/технологий в базу данных")
    return saved_count

def get_all_episodes():
    """Получить список всех эпизодов из базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT id, episode_number, title, published_date, processed 
    FROM episodes 
    ORDER BY episode_number DESC
    """)
    
    episodes = []
    for row in cursor.fetchall():
        episodes.append({
            "id": row[0],
            "episode_number": row[1],
            "title": row[2],
            "published_date": row[3],
            "processed": row[4]
        })
    
    conn.close()
    return episodes

def get_episode_recommendations(episode_id):
    """Получить рекомендации для конкретного эпизода"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT id, product_name, description, mentioned_by, hosts_opinion, 
           ai_comment, website, timestamp, confidence
    FROM recommendations
    WHERE episode_id = ?
    ORDER BY id
    """, (episode_id,))
    
    recommendations = []
    for row in cursor.fetchall():
        recommendations.append({
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "mentioned_by": row[3],
            "hosts_opinion": row[4],
            "ai_comment": row[5],
            "website": row[6],
            "timestamp": row[7],
            "confidence": row[8]
        })
    
    conn.close()
    return recommendations

def search_recommendations(search_term):
    """Поиск рекомендаций по ключевому слову"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    search_pattern = f"%{search_term}%"
    
    cursor.execute("""
    SELECT r.id, e.episode_number, r.product_name, r.description,
           r.mentioned_by, r.hosts_opinion, r.ai_comment, r.website
    FROM recommendations r
    JOIN episodes e ON r.episode_id = e.id
    WHERE r.product_name LIKE ? OR r.description LIKE ?
    ORDER BY e.episode_number DESC
    """, (search_pattern, search_pattern))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0],
            "episode_number": row[1],
            "name": row[2],
            "description": row[3],
            "mentioned_by": row[4],
            "hosts_opinion": row[5],
            "ai_comment": row[6],
            "website": row[7]
        })
    
    conn.close()
    return results 