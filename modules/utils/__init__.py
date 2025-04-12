"""
Модуль, содержащий вспомогательные функции и утилиты
"""

import os
import logging
from .database import get_all_episodes

def recover_episodes():
    """
    Восстановление информации об эпизодах на основе существующих файлов
    
    Returns:
        list: Список восстановленных эпизодов или None, если восстановление не требуется
    """
    return get_all_episodes() 