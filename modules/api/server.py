"""
Веб-интерфейс на FastAPI для управления процессом транскрибирования
"""

import os
import json
import logging
from typing import List, Optional
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from modules.core.podcast import (
    get_latest_episode, get_all_episodes_from_rss, 
    get_episode_status, process_episode, HOSTS
)
from modules.utils.database import (
    init_db, get_all_episodes, get_episode_recommendations,
    search_recommendations
)
from modules.utils import recover_episodes

# Настройка логирования
logger = logging.getLogger(__name__)

# Создание директории для шаблонов, если она не существует
os.makedirs("modules/api/templates", exist_ok=True)

# Создание директории для статических файлов, если она не существует
os.makedirs("modules/api/static", exist_ok=True)

# Инициализация FastAPI
app = FastAPI(title="Радио-Т Транскрибер", description="Веб-интерфейс для управления транскрибированием подкаста Радио-Т")

# Настройка статических файлов и шаблонов
app.mount("/static", StaticFiles(directory="modules/api/static"), name="static")
templates = Jinja2Templates(directory="modules/api/templates")

# Модели данных
class Episode(BaseModel):
    episode_number: int
    title: str
    published_date: str
    processed: int
    status: Optional[dict] = None

class Recommendation(BaseModel):
    id: int
    name: str
    description: str
    mentioned_by: Optional[str] = None
    hosts_opinion: Optional[str] = None
    ai_comment: Optional[str] = None
    website: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: Optional[int] = None

# Фоновые задачи
running_tasks = {}

async def process_episode_task(episode_number: int, force_retranscribe: bool = False):
    """Фоновая задача для обработки эпизода"""
    task_id = f"episode_{episode_number}"
    running_tasks[task_id] = {"status": "running", "progress": 0, "message": "Начало обработки эпизода"}
    
    try:
        # Запуск обработки эпизода
        running_tasks[task_id]["message"] = "Обработка эпизода..."
        result = process_episode(episode_number, force_retranscribe)
        
        if result:
            running_tasks[task_id]["status"] = "completed"
            running_tasks[task_id]["progress"] = 100
            running_tasks[task_id]["message"] = "Эпизод успешно обработан"
        else:
            running_tasks[task_id]["status"] = "failed"
            running_tasks[task_id]["message"] = "При обработке эпизода возникли ошибки"
    except Exception as e:
        running_tasks[task_id]["status"] = "failed"
        running_tasks[task_id]["message"] = f"Ошибка: {str(e)}"
        logger.error(f"Ошибка при обработке эпизода #{episode_number}: {str(e)}")

# Маршруты
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница"""
    # Инициализация базы данных, если необходимо
    init_db()
    
    # Получение списка эпизодов
    episodes = get_all_episodes()
    
    # Обогащение информацией о статусе файлов
    for ep in episodes:
        ep["status"] = get_episode_status(ep["episode_number"])
    
    # Получение последнего эпизода из RSS
    latest_episode = get_latest_episode()
    
    # Получение списка последних эпизодов из RSS
    rss_episodes = get_all_episodes_from_rss(10)
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "episodes": episodes,
            "latest_episode": latest_episode,
            "rss_episodes": rss_episodes
        }
    )

@app.get("/episodes", response_model=List[Episode])
async def get_episodes():
    """Получение списка всех эпизодов"""
    episodes = get_all_episodes()
    return episodes

@app.get("/episodes/{episode_number}", response_class=JSONResponse)
async def get_episode_json(episode_number: int):
    """Получение информации о конкретном эпизоде в формате JSON"""
    episodes = get_all_episodes()
    
    # Поиск эпизода в базе данных
    episode = None
    for ep in episodes:
        if ep["episode_number"] == episode_number:
            episode = ep
            break
    
    if not episode:
        raise HTTPException(status_code=404, detail=f"Эпизод #{episode_number} не найден")
    
    # Получение статуса файлов
    episode["status"] = get_episode_status(episode_number)
    
    # Получение рекомендаций
    recommendations = get_episode_recommendations(episode["id"])
    
    return {"episode": episode, "recommendations": recommendations}

@app.get("/episodes/{episode_number}/details", response_class=HTMLResponse)
async def episode_details_page(request: Request, episode_number: int):
    """Страница с детальной информацией об эпизоде"""
    episodes = get_all_episodes()
    
    # Поиск эпизода в базе данных
    episode = None
    for ep in episodes:
        if ep["episode_number"] == episode_number:
            episode = ep
            break
    
    if not episode:
        raise HTTPException(status_code=404, detail=f"Эпизод #{episode_number} не найден")
    
    # Получение статуса файлов
    episode["status"] = get_episode_status(episode_number)
    
    # Получение рекомендаций
    recommendations = get_episode_recommendations(episode["id"])
    
    # Получение статуса задач для этого эпизода
    task_id = f"episode_{episode_number}"
    task_status = None
    if task_id in running_tasks:
        task_status = running_tasks[task_id]
    
    return templates.TemplateResponse(
        "episode_details.html",
        {
            "request": request,
            "episode": episode,
            "recommendations": recommendations,
            "task_status": task_status
        }
    )

@app.post("/episodes/{episode_number}/process")
async def process_episode_route(episode_number: int, background_tasks: BackgroundTasks, force_retranscribe: bool = False):
    """Запуск обработки эпизода"""
    task_id = f"episode_{episode_number}"
    
    # Проверка, не запущена ли уже обработка
    if task_id in running_tasks and running_tasks[task_id]["status"] == "running":
        return {"message": f"Обработка эпизода #{episode_number} уже выполняется"}
    
    # Запуск обработки в фоновом режиме
    background_tasks.add_task(process_episode_task, episode_number, force_retranscribe)
    running_tasks[task_id] = {"status": "running", "progress": 0, "message": "Задача поставлена в очередь"}
    
    return {"message": f"Запущена обработка эпизода #{episode_number}"}

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Получение статуса выполнения задачи"""
    if task_id not in running_tasks:
        raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
    
    return running_tasks[task_id]

@app.get("/search")
async def search(query: str):
    """Поиск по рекомендациям"""
    if not query or len(query) < 2:
        return {"results": []}
    
    results = search_recommendations(query)
    return {"results": results}

@app.get("/rss")
async def get_rss_episodes():
    """Получение списка эпизодов из RSS"""
    episodes = get_all_episodes_from_rss(20)
    return {"episodes": episodes}

@app.get("/episodes/{episode_number}/recommendations", response_class=HTMLResponse)
async def episode_recommendations_page(request: Request, episode_number: int):
    """Страница с рекомендациями для конкретного эпизода"""
    episodes = get_all_episodes()
    
    # Поиск эпизода в базе данных
    episode = None
    for ep in episodes:
        if ep["episode_number"] == episode_number:
            episode = ep
            break
    
    if not episode:
        raise HTTPException(status_code=404, detail=f"Эпизод #{episode_number} не найден")
    
    # Получение статуса файлов
    episode["status"] = get_episode_status(episode_number)
    
    # Получение рекомендаций
    recommendations = get_episode_recommendations(episode["id"])
    
    return templates.TemplateResponse(
        "recommendations.html",
        {
            "request": request,
            "episode": episode,
            "recommendations": recommendations,
            "hosts": HOSTS
        }
    )

# Создание базового HTML шаблона
def create_template_files():
    """Создание файлов шаблонов, если они не существуют"""
    index_html = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Радио-Т Транскрибер</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root {
                --primary-color: #0d6efd;
                --accent-color: #6f42c1;
                --success-color: #198754;
                --light-bg: #f8f9fa;
            }
            body {
                background-color: #f5f5f7;
            }
            .container {
                max-width: 1200px;
            }
            .episode-card {
                margin-bottom: 15px;
                transition: all 0.3s;
                height: 100%;
                border-radius: 10px;
                border: none;
                box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            }
            .episode-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            }
            .status-badge {
                margin-right: 5px;
                padding: 5px 10px;
                border-radius: 20px;
                font-weight: normal;
            }
            .recommendation-card {
                margin-bottom: 15px;
                border-radius: 10px;
                transition: all 0.3s;
                height: 100%;
                border: none;
                box-shadow: 0 2px 5px rgba(0,0,0,0.05);
                overflow: hidden;
            }
            .recommendation-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 8px 15px rgba(0,0,0,0.1);
            }
            .recommendation-header {
                font-weight: 600;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
                margin-bottom: 10px;
                color: var(--primary-color);
            }
            .recommendation-meta {
                font-size: 0.85rem;
                color: #666;
                margin-top: 10px;
            }
            .recommendation-meta a {
                color: var(--accent-color);
                text-decoration: none;
                word-break: break-all;
            }
            .recommendation-meta a:hover {
                text-decoration: underline;
            }
            .rss-episode-card {
                background-color: white;
                border-left: 4px solid var(--primary-color);
            }
            .section-title {
                margin-top: 40px;
                margin-bottom: 25px;
                border-bottom: 2px solid var(--primary-color);
                padding-bottom: 10px;
                color: #333;
                font-weight: bold;
            }
            .truncate-2 {
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .truncate-3 {
                display: -webkit-box;
                -webkit-line-clamp: 3;
                -webkit-box-orient: vertical;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .card-header {
                font-weight: bold;
                letter-spacing: 0.5px;
            }
            .btn {
                border-radius: 20px;
                padding: 6px 15px;
            }
            .btn-sm {
                border-radius: 15px;
                padding: 4px 12px;
            }
            .website-link {
                display: block;
                margin-top: 5px;
                padding: 5px 10px;
                background-color: #f5f5f5;
                border-radius: 5px;
                word-break: break-all;
            }
            .unprocessed-episode {
                border-left: 4px solid var(--accent-color);
            }
            .processed-episode {
                border-left: 4px solid var(--success-color);
            }
        </style>
    </head>
    <body>
        <div class="container mt-4 mb-5">
            <h1 class="mb-4">Радио-Т Транскрибер</h1>
            
            <div class="row mb-4">
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header bg-primary text-white">
                            Последний эпизод
                        </div>
                        <div class="card-body">
                            {% if latest_episode %}
                                <h5 class="card-title">Эпизод #{{ latest_episode.episode_number }}: {{ latest_episode.title }}</h5>
                                <p class="card-text">Дата публикации: {{ latest_episode.published_date }}</p>
                                
                                {% set status = namespace(found=false) %}
                                {% for ep in episodes %}
                                    {% if ep.episode_number == latest_episode.episode_number %}
                                        {% set status.found = true %}
                                        <div class="mb-3">
                                            <span class="badge bg-success status-badge">В базе данных</span>
                                            
                                            {% if ep.status.downloaded %}
                                                <span class="badge bg-success status-badge">Скачан</span>
                                            {% else %}
                                                <span class="badge bg-danger status-badge">Не скачан</span>
                                            {% endif %}
                                            
                                            {% if ep.status.transcribed %}
                                                <span class="badge bg-success status-badge">Транскрибирован</span>
                                            {% else %}
                                                <span class="badge bg-danger status-badge">Не транскрибирован</span>
                                            {% endif %}
                                            
                                            {% if ep.status.recommendations %}
                                                <span class="badge bg-success status-badge">Рекомендации извлечены</span>
                                            {% else %}
                                                <span class="badge bg-danger status-badge">Рекомендации не извлечены</span>
                                            {% endif %}
                                        </div>
                                        
                                        <button class="btn btn-primary process-episode" data-episode="{{ latest_episode.episode_number }}">
                                            {% if ep.status.processed < 2 %}
                                                Продолжить обработку
                                            {% else %}
                                                Обработать заново
                                            {% endif %}
                                        </button>
                                        <a href="/episodes/{{ latest_episode.episode_number }}/details" class="btn btn-secondary">Подробнее</a>
                                    {% endif %}
                                {% endfor %}
                                
                                {% if not status.found %}
                                    <div class="mb-3">
                                        <span class="badge bg-warning status-badge">Новый эпизод</span>
                                        <span class="badge bg-danger status-badge">Не обработан</span>
                                    </div>
                                    <button class="btn btn-primary process-episode" data-episode="{{ latest_episode.episode_number }}">Обработать эпизод</button>
                                {% endif %}
                            {% else %}
                                <p class="card-text">Не удалось получить информацию о последнем эпизоде.</p>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="row mb-4">
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header bg-secondary text-white">
                            Поиск по рекомендациям
                        </div>
                        <div class="card-body">
                            <div class="input-group mb-3">
                                <input type="text" id="search-input" class="form-control" placeholder="Введите поисковый запрос...">
                                <button class="btn btn-primary" id="search-button">Поиск</button>
                            </div>
                            <div id="search-results" class="mt-3">
                                <!-- Результаты поиска будут здесь -->
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Последние эпизоды из RSS, доступные для обработки -->
            <h2 class="section-title">Последние эпизоды в RSS</h2>
            <div class="row">
                {% for episode in rss_episodes %}
                    <div class="col-md-4 mb-4">
                        {% set ep_status = namespace(found=false, processed=0) %}
                        {% for ep in episodes %}
                            {% if ep.episode_number == episode.episode_number %}
                                {% set ep_status.found = true %}
                                {% set ep_status.processed = ep.processed %}
                            {% endif %}
                        {% endfor %}
                        
                        <div class="card episode-card rss-episode-card {% if ep_status.found %}processed-episode{% else %}unprocessed-episode{% endif %}">
                            <div class="card-body">
                                <h5 class="card-title">Эпизод #{{ episode.episode_number }}</h5>
                                <h6 class="card-subtitle mb-2 text-muted truncate-2">{{ episode.title }}</h6>
                                <p class="card-text">
                                    <small>Дата: {{ episode.published_date }}</small>
                                </p>
                                
                                <div class="mb-2">
                                    {% if ep_status.found %}
                                        {% for ep in episodes %}
                                            {% if ep.episode_number == episode.episode_number %}
                                                {% if ep.status.downloaded %}
                                                    <span class="badge bg-success status-badge">Скачан</span>
                                                {% else %}
                                                    <span class="badge bg-danger status-badge">Не скачан</span>
                                                {% endif %}
                                                
                                                {% if ep.status.transcribed %}
                                                    <span class="badge bg-success status-badge">Транскрибирован</span>
                                                {% else %}
                                                    <span class="badge bg-danger status-badge">Не транскрибирован</span>
                                                {% endif %}
                                                
                                                {% if ep.status.recommendations %}
                                                    <span class="badge bg-success status-badge">Рекомендации</span>
                                                {% else %}
                                                    <span class="badge bg-danger status-badge">Нет рекомендаций</span>
                                                {% endif %}
                                            {% endif %}
                                        {% endfor %}
                                    {% else %}
                                        <span class="badge bg-warning status-badge">Не обработан</span>
                                    {% endif %}
                                </div>
                                
                                <div class="d-flex justify-content-between">
                                    {% if ep_status.found %}
                                        <div class="btn-group">
                                            <a href="/episodes/{{ episode.episode_number }}/details" class="btn btn-sm btn-secondary">Подробнее</a>
                                            {% if ep_status.found and ep_status.processed > 1 %}
                                            <a href="/episodes/{{ episode.episode_number }}/recommendations" class="btn btn-sm btn-info">
                                                <i class="fas fa-list-ul"></i> Рекомендации
                                            </a>
                                            {% endif %}
                                        </div>
                                        <button class="btn btn-sm btn-primary process-episode" data-episode="{{ episode.episode_number }}">
                                            {% if ep_status.processed < 2 %}
                                                Продолжить обработку
                                            {% else %}
                                                Обновить
                                            {% endif %}
                                        </button>
                                    {% else %}
                                        <button class="btn btn-sm btn-success process-episode" data-episode="{{ episode.episode_number }}">
                                            Обработать
                                        </button>
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                    </div>
                {% endfor %}
            </div>
            
            <!-- Обработанные эпизоды -->
            <h2 class="section-title">Обработанные эпизоды</h2>
            <div class="row">
                {% for episode in episodes %}
                    <div class="col-md-4 mb-4">
                        <div class="card episode-card processed-episode">
                            <div class="card-body">
                                <h5 class="card-title">Эпизод #{{ episode.episode_number }}</h5>
                                <h6 class="card-subtitle mb-2 text-muted truncate-2">{{ episode.title }}</h6>
                                <p class="card-text">
                                    <small>Дата: {{ episode.published_date }}</small>
                                </p>
                                
                                <div class="mb-2">
                                    {% if episode.status.downloaded %}
                                        <span class="badge bg-success status-badge">Скачан</span>
                                    {% else %}
                                        <span class="badge bg-danger status-badge">Не скачан</span>
                                    {% endif %}
                                    
                                    {% if episode.status.transcribed %}
                                        <span class="badge bg-success status-badge">Транскрибирован</span>
                                    {% else %}
                                        <span class="badge bg-danger status-badge">Не транскрибирован</span>
                                    {% endif %}
                                    
                                    {% if episode.status.recommendations %}
                                        <span class="badge bg-success status-badge">Рекомендации</span>
                                    {% else %}
                                        <span class="badge bg-danger status-badge">Нет рекомендаций</span>
                                    {% endif %}
                                </div>
                                
                                <div class="d-flex justify-content-between">
                                    <div class="btn-group">
                                        <a href="/episodes/{{ episode.episode_number }}/details" class="btn btn-sm btn-secondary">Подробнее</a>
                                        {% if episode.status.recommendations %}
                                        <a href="/episodes/{{ episode.episode_number }}/recommendations" class="btn btn-sm btn-info">
                                            <i class="fas fa-list-ul"></i> Рекомендации
                                        </a>
                                        {% endif %}
                                    </div>
                                    <button class="btn btn-sm btn-primary process-episode" data-episode="{{ episode.episode_number }}">
                                        {% if episode.processed < 2 %}
                                            Обработать
                                        {% else %}
                                            Обновить
                                        {% endif %}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                {% endfor %}
            </div>
        </div>
        
        <!-- Модальное окно для отображения статуса задачи -->
        <div class="modal fade" id="taskModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Обработка эпизода</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <div class="progress mb-3">
                            <div class="progress-bar" role="progressbar" style="width: 0%"></div>
                        </div>
                        <p id="task-status">Задача поставлена в очередь...</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Закрыть</button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Шаблон для страницы детальной информации о эпизоде -->
        <template id="episode-detail-template">
            <div class="container mt-4 mb-5">
                <div class="row mb-4">
                    <div class="col-12">
                        <nav aria-label="breadcrumb">
                            <ol class="breadcrumb">
                                <li class="breadcrumb-item"><a href="/">Главная</a></li>
                                <li class="breadcrumb-item active" aria-current="page">Эпизод #</li>
                            </ol>
                        </nav>
                    </div>
                </div>
                
                <div class="row mb-4">
                    <div class="col-12">
                        <div class="card">
                            <div class="card-header bg-primary text-white">
                                Информация об эпизоде
                            </div>
                            <div class="card-body" id="episode-info">
                                <!-- Сюда будет добавлена информация о эпизоде -->
                            </div>
                        </div>
                    </div>
                </div>
                
                <h2 class="section-title">Рекомендации из эпизода</h2>
                <div class="row" id="recommendations-container">
                    <!-- Сюда будут добавлены карточки рекомендаций -->
                </div>
            </div>
        </template>
        
        <!-- Шаблон для карточки рекомендации -->
        <template id="recommendation-card-template">
            <div class="col-md-4 mb-4">
                <div class="card recommendation-card">
                    <div class="card-body">
                        <h5 class="recommendation-header"></h5>
                        <p class="card-text description truncate-3"></p>
                        <div class="recommendation-meta">
                            <p class="mentioned-by mb-1"><i class="fas fa-user me-1"></i> <span></span></p>
                            <p class="hosts-opinion mb-1"><i class="fas fa-comment me-1"></i> <span></span></p>
                            <p class="website mb-1"><i class="fas fa-globe me-1"></i> <a href="#" target="_blank" rel="noopener noreferrer"></a></p>
                        </div>
                    </div>
                </div>
            </div>
        </template>
        
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/js/bootstrap.bundle.min.js"></script>
        <script>
            // Обработка запуска обработки эпизода
            document.querySelectorAll('.process-episode').forEach(button => {
                button.addEventListener('click', async (e) => {
                    const episodeNumber = e.target.dataset.episode;
                    
                    // Показываем модальное окно
                    const taskModal = new bootstrap.Modal(document.getElementById('taskModal'));
                    taskModal.show();
                    
                    // Запускаем обработку
                    try {
                        const response = await fetch(`/episodes/${episodeNumber}/process`, {
                            method: 'POST',
                        });
                        const data = await response.json();
                        
                        // Начинаем опрос статуса
                        const taskId = `episode_${episodeNumber}`;
                        pollTaskStatus(taskId);
                    } catch (error) {
                        document.getElementById('task-status').textContent = `Ошибка: ${error.message}`;
                    }
                });
            });
            
            // Функция для опроса статуса задачи
            function pollTaskStatus(taskId) {
                const interval = setInterval(async () => {
                    try {
                        const response = await fetch(`/tasks/${taskId}`);
                        const data = await response.json();
                        
                        // Обновляем прогресс и статус
                        document.querySelector('.progress-bar').style.width = `${data.progress}%`;
                        document.getElementById('task-status').textContent = data.message;
                        
                        // Если задача завершена, останавливаем опрос
                        if (data.status === 'completed' || data.status === 'failed') {
                            clearInterval(interval);
                            
                            // Если успешно, предлагаем обновить страницу
                            if (data.status === 'completed') {
                                setTimeout(() => {
                                    if (confirm('Обработка завершена. Обновить страницу?')) {
                                        window.location.reload();
                                    }
                                }, 1000);
                            }
                        }
                    } catch (error) {
                        document.getElementById('task-status').textContent = `Ошибка при получении статуса: ${error.message}`;
                        clearInterval(interval);
                    }
                }, 1000);
            }
            
            // Обработка поиска
            document.getElementById('search-button').addEventListener('click', async () => {
                const query = document.getElementById('search-input').value.trim();
                
                if (query.length < 2) {
                    document.getElementById('search-results').innerHTML = '<div class="alert alert-warning">Введите минимум 2 символа для поиска</div>';
                    return;
                }
                
                document.getElementById('search-results').innerHTML = '<div class="text-center"><div class="spinner-border" role="status"></div></div>';
                
                try {
                    const response = await fetch(`/search?query=${encodeURIComponent(query)}`);
                    const data = await response.json();
                    
                    if (data.results.length === 0) {
                        document.getElementById('search-results').innerHTML = '<div class="alert alert-info">По вашему запросу ничего не найдено</div>';
                        return;
                    }
                    
                    let resultsHtml = '<div class="row">';
                    
                    data.results.forEach(result => {
                        resultsHtml += `
                            <div class="col-md-4 mb-4">
                                <div class="card recommendation-card">
                                    <div class="card-body">
                                        <h5 class="recommendation-header">${result.name}</h5>
                                        <p class="card-text truncate-3">${result.description}</p>
                                        <div class="recommendation-meta">
                                            ${result.mentioned_by && result.mentioned_by.toLowerCase() !== 'unknown' ? 
                                                `<p class="mentioned-by mb-1"><i class="fas fa-user me-1"></i> ${result.mentioned_by}</p>` : ''}
                                            ${result.hosts_opinion ? 
                                                `<p class="hosts-opinion mb-1"><i class="fas fa-comment me-1"></i> ${result.hosts_opinion}</p>` : ''}
                                            ${result.website ? 
                                                `<p class="website mb-1"><i class="fas fa-globe me-1"></i> <a href="${result.website}" target="_blank" rel="noopener noreferrer">${result.website}</a></p>` : ''}
                                        </div>
                                        <p class="mt-2"><small>Эпизод #${result.episode_number}</small></p>
                                        <a href="/episodes/${result.episode_number}/details" class="btn btn-sm btn-outline-secondary">Подробнее</a>
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    
                    resultsHtml += '</div>';
                    document.getElementById('search-results').innerHTML = resultsHtml;
                } catch (error) {
                    document.getElementById('search-results').innerHTML = `<div class="alert alert-danger">Ошибка при поиске: ${error.message}</div>`;
                }
            });
            
            // Обработка нажатия Enter в поле поиска
            document.getElementById('search-input').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    document.getElementById('search-button').click();
                }
            });
            
            // Проверяем, находимся ли мы на странице с деталями эпизода
            if (window.location.pathname.startsWith('/episodes/')) {
                const episodeNumber = window.location.pathname.split('/').pop();
                loadEpisodeDetails(episodeNumber);
            }
            
            // Функция для загрузки деталей эпизода
            async function loadEpisodeDetails(episodeNumber) {
                try {
                    const response = await fetch(`/episodes/${episodeNumber}`);
                    const data = await response.json();
                    
                    // Клонируем шаблон
                    const template = document.getElementById('episode-detail-template');
                    const content = template.content.cloneNode(true);
                    
                    // Заполняем информацию об эпизоде
                    document.title = `Эпизод #${data.episode.episode_number} — Радио-Т Транскрибер`;
                    
                    content.querySelector('.breadcrumb-item.active').textContent = `Эпизод #${data.episode.episode_number}`;
                    
                    const episodeInfo = `
                        <h3>Эпизод #${data.episode.episode_number}: ${data.episode.title}</h3>
                        <p>Дата публикации: ${data.episode.published_date}</p>
                        
                        <div class="mb-3">
                            ${data.episode.status.downloaded ? 
                                '<span class="badge bg-success status-badge">Скачан</span>' : 
                                '<span class="badge bg-danger status-badge">Не скачан</span>'}
                                
                            ${data.episode.status.transcribed ? 
                                '<span class="badge bg-success status-badge">Транскрибирован</span>' : 
                                '<span class="badge bg-danger status-badge">Не транскрибирован</span>'}
                                
                            ${data.episode.status.recommendations ? 
                                '<span class="badge bg-success status-badge">Рекомендации извлечены</span>' : 
                                '<span class="badge bg-danger status-badge">Рекомендации не извлечены</span>'}
                        </div>
                        
                        <button class="btn btn-primary process-episode" data-episode="${data.episode.episode_number}">
                            ${data.episode.processed < 2 ? 'Продолжить обработку' : 'Обработать заново'}
                        </button>
                    `;
                    
                    content.querySelector('#episode-info').innerHTML = episodeInfo;
                    
                    // Заполняем рекомендации
                    const recommendationsContainer = content.querySelector('#recommendations-container');
                    const cardTemplate = document.getElementById('recommendation-card-template');
                    
                    if (data.recommendations.length === 0) {
                        recommendationsContainer.innerHTML = '<div class="col-12"><div class="alert alert-info">У этого эпизода пока нет рекомендаций</div></div>';
                    } else {
                        // Добавляем кнопку для перехода на страницу рекомендаций
                        const viewAllButton = document.createElement('div');
                        viewAllButton.className = 'col-12 mb-4 text-center';
                        viewAllButton.innerHTML = `
                            <a href="/episodes/${data.episode.episode_number}/recommendations" class="btn btn-primary">
                                <i class="fas fa-th-large me-2"></i> Просмотреть все рекомендации в виде карточек
                            </a>
                        `;
                        recommendationsContainer.appendChild(viewAllButton);
                        
                        // Выводим первые 6 рекомендаций
                        const previewRecommendations = data.recommendations.slice(0, 6);
                        
                        previewRecommendations.forEach(rec => {
                            const card = cardTemplate.content.cloneNode(true);
                            card.querySelector('.recommendation-header').textContent = rec.name;
                            card.querySelector('.description').textContent = rec.description;
                            
                            if (rec.mentioned_by && rec.mentioned_by.toLowerCase() !== 'unknown') {
                                card.querySelector('.mentioned-by span').textContent = rec.mentioned_by;
                            } else {
                                card.querySelector('.mentioned-by').style.display = 'none';
                            }
                            
                            if (rec.hosts_opinion) {
                                card.querySelector('.hosts-opinion span').textContent = rec.hosts_opinion;
                            } else {
                                card.querySelector('.hosts-opinion').style.display = 'none';
                            }
                            
                            if (rec.website) {
                                const link = card.querySelector('.website a');
                                link.href = rec.website;
                                link.textContent = rec.website;
                                
                                // Кликабельная ссылка, открывающаяся в новом окне
                                link.setAttribute('target', '_blank');
                                link.setAttribute('rel', 'noopener noreferrer');
                            } else {
                                card.querySelector('.website').style.display = 'none';
                            }
                            
                            recommendationsContainer.appendChild(card);
                        });
                        
                        // Добавляем уведомление, если есть больше рекомендаций
                        if (data.recommendations.length > 6) {
                            const moreRecsNotice = document.createElement('div');
                            moreRecsNotice.className = 'col-12 mt-3 text-center';
                            moreRecsNotice.innerHTML = `
                                <div class="alert alert-info">
                                    <i class="fas fa-info-circle me-2"></i> Показаны 6 из ${data.recommendations.length} рекомендаций. 
                                    Перейдите на страницу рекомендаций, чтобы увидеть все.
                                </div>
                            `;
                            recommendationsContainer.appendChild(moreRecsNotice);
                        }
                    }
                    
                    // Заменяем содержимое страницы
                    document.body.innerHTML = '';
                    document.body.appendChild(content);
                    
                    // Добавляем обработчики событий
                    document.querySelectorAll('.process-episode').forEach(button => {
                        button.addEventListener('click', async (e) => {
                            const episodeNumber = e.target.dataset.episode;
                            
                            try {
                                const response = await fetch(`/episodes/${episodeNumber}/process`, {
                                    method: 'POST',
                                });
                                const data = await response.json();
                                
                                alert(`Запущена обработка эпизода #${episodeNumber}. Это может занять некоторое время.`);
                            } catch (error) {
                                alert(`Ошибка: ${error.message}`);
                            }
                        });
                    });
                    
                } catch (error) {
                    console.error('Ошибка при загрузке деталей эпизода:', error);
                    document.body.innerHTML = `<div class="container mt-4"><div class="alert alert-danger">Ошибка при загрузке данных: ${error.message}</div></div>`;
                }
            }
        </script>
    </body>
    </html>
    """
    
    # Создаем файл шаблона, если он не существует
    template_path = os.path.join("modules/api/templates", "index.html")
    if not os.path.exists(template_path):
        os.makedirs(os.path.dirname(template_path), exist_ok=True)
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(index_html)

def start_server():
    """Запуск веб-сервера"""
    # Создание файлов шаблонов
    create_template_files()
    
    # Инициализация базы данных
    init_db()
    
    # Восстановление информации об эпизодах на основе существующих файлов
    logger.info("Запуск процесса восстановления данных об эпизодах...")
    recovered = get_all_episodes()
    if recovered:
        logger.info(f"Получено {len(recovered)} эпизодов из базы данных")
    else:
        logger.info("В базе данных нет эпизодов")
    
    # Запуск веб-сервера
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    start_server() 