#!/usr/bin/env python3
"""
Основной скрипт для запуска ВСЕХ парсеров, обработки результатов
и отправки НОВЫХ объявлений в Telegram.
(Находится внутри папки UruguayLands)
"""

import asyncio
import os
import logging
from pathlib import Path
import sys
import json
from typing import List, Set, Type

from dotenv import load_dotenv

# --- ЯВНОЕ ДОБАВЛЕНИЕ ПУТЕЙ --- 
# Определяем корень UruguayLands как директорию, где находится этот скрипт
URUGUAYLANDS_ROOT = Path(__file__).parent.resolve()
# Добавляем корень UruguayLands в sys.path, чтобы можно было импортировать config и app
if str(URUGUAYLANDS_ROOT) not in sys.path:
    sys.path.insert(0, str(URUGUAYLANDS_ROOT))
# Добавляем корень всего проекта (на уровень выше UruguayLands) для импорта из папки parsers
PROJECT_ROOT = URUGUAYLANDS_ROOT.parent 
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------

# --- Настройка базового логгирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MainRunner")

# --- Загрузка конфигурации --- 
# Ищем .env в UruguayLands/config/.env
dotenv_path = URUGUAYLANDS_ROOT / 'config' / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
    logger.info(f"Переменные окружения загружены из {dotenv_path}.")
else:
    logger.warning(f".env файл не найден по пути: {dotenv_path}. Используются переменные окружения системы.")
    # Пытаемся загрузить из переменных окружения системы
    load_dotenv()

# --- Импорт компонентов приложения --- 
try:
    # Импорты теперь ОТНОСИТЕЛЬНО ПАПКИ UruguayLands
    from config import settings
    from app.telegram_poster import post_to_telegram
    from app.parsers.base import BaseParser
    from app.models import Listing
    from app.parsers.gallito import GallitoParser
    from app.parsers.infocasas import InfoCasasParser
    # from app.parsers.mercadolibre import MercadoLibreParser 
except ImportError as e:
    logger.error(f"Не удалось импортировать необходимый компонент: {e}. Проверьте структуру проекта и импорты.", exc_info=True)
    logger.error(f"Текущий sys.path: {sys.path}")
    sys.exit(1)
except Exception as e:
    logger.error(f"Неожиданная ошибка во время импорта: {e}", exc_info=True)
    sys.exit(1)

# --- Константы --- 
# Файл истории в папке data внутри UruguayLands
HISTORY_FILE_PATH = URUGUAYLANDS_ROOT / "data" / "sent_listings_history.json"
PARSERS_TO_RUN: List[Type[BaseParser]] = [
    GallitoParser,
    InfoCasasParser,
    # MercadoLibreParser # <-- Раскомментируйте, когда он будет готов
]

# --- Функции управления историей ---
def load_sent_history() -> Set[str]:
    """Загружает набор URL уже отправленных объявлений из JSON файла."""
    if not HISTORY_FILE_PATH.exists():
        logger.info(f"Файл истории {HISTORY_FILE_PATH} не найден, создается пустая история.")
        return set()
    try:
        with open(HISTORY_FILE_PATH, 'r', encoding='utf-8') as f:
            urls = json.load(f)
            if isinstance(urls, list):
                 logger.info(f"Загружено {len(urls)} URL из истории.")
                 return set(urls)
            else:
                 logger.warning(f"Файл истории {HISTORY_FILE_PATH} имеет неверный формат (ожидался список). Используется пустая история.")
                 return set()
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в файле истории {HISTORY_FILE_PATH}. Используется пустая история.")
        return set()
    except Exception as e:
        logger.error(f"Не удалось загрузить файл истории {HISTORY_FILE_PATH}: {e}. Используется пустая история.", exc_info=True)
        return set()

def save_sent_history(sent_urls: Set[str]):
    """Сохраняет набор URL отправленных объявлений в JSON файл."""
    try:
        # Создаем папку data, если ее нет
        HISTORY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(sorted(list(sent_urls)), f, ensure_ascii=False, indent=4)
        logger.info(f"История {len(sent_urls)} отправленных URL успешно сохранена в {HISTORY_FILE_PATH}.")
    except Exception as e:
        logger.error(f"Не удалось сохранить файл истории {HISTORY_FILE_PATH}: {e}", exc_info=True)

# --- Основная асинхронная функция ---
async def main():
    logger.info("--- Запуск основного цикла обработки объявлений ---")
    sent_urls_history = load_sent_history()
    all_listings: List[Listing] = []
    parser_tasks = []

    # Создаем задачи для запуска каждого парсера
    for ParserClass in PARSERS_TO_RUN:
        try:
            parser_instance = ParserClass()
            logger.info(f"Запуск парсера: {parser_instance.SOURCE_NAME}...")
            max_pages = getattr(settings, 'MAX_PAGES_PER_SOURCE', 1)
            parser_tasks.append(parser_instance.run(max_pages=max_pages, headless=False))
        except Exception as e:
            logger.error(f"Ошибка при инициализации парсера {ParserClass.__name__}: {e}", exc_info=True)

    # Запускаем парсеры параллельно и собираем результаты
    if parser_tasks:
        try:
            results = await asyncio.gather(*parser_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                ParserClass = PARSERS_TO_RUN[i]
                if isinstance(result, Exception):
                    logger.error(f"Парсер {ParserClass.__name__} завершился с ошибкой: {result}", exc_info=result)
                elif isinstance(result, list):
                    logger.info(f"Парсер {ParserClass.__name__} успешно вернул {len(result)} объявлений.")
                    all_listings.extend(result)
                else:
                     logger.warning(f"Парсер {ParserClass.__name__} вернул неожиданный результат типа {type(result)}.")
        except Exception as e:
            logger.error(f"Ошибка во время параллельного выполнения парсеров: {e}", exc_info=True)

    logger.info(f"Всего получено {len(all_listings)} объявлений со всех источников.")

    # Фильтрация новых объявлений
    new_listings = [listing for listing in all_listings if str(listing.url) not in sent_urls_history]
    logger.info(f"Найдено {len(new_listings)} новых объявлений для отправки.")

    # Отправка новых объявлений
    if not new_listings:
        logger.info("Нет новых объявлений для отправки.")
    else:
        logger.info(f"Начинается отправка {len(new_listings)} новых объявлений в Telegram...")
        newly_sent_urls = set()
        telegram_delay = getattr(settings, 'TELEGRAM_DELAY_SECONDS', 5)

        for i, listing in enumerate(new_listings):
            logger.info(f"--- Отправка {i+1}/{len(new_listings)}: {listing.title} ({listing.url}) ---")
            try:
                listing_dict = listing.model_dump()
                if isinstance(listing_dict.get('image_url'), object) and hasattr(listing_dict['image_url'], 'unicode_string'):
                     listing_dict['image_url'] = listing_dict['image_url'].unicode_string()

                success = await post_to_telegram(listing_dict)
                if success:
                    logger.info(f"Объявление {listing.url} успешно отправлено.")
                    newly_sent_urls.add(str(listing.url))
                    if i < len(new_listings) - 1:
                        logger.info(f"Пауза {telegram_delay} сек...")
                        await asyncio.sleep(telegram_delay)
                else:
                    logger.warning(f"Не удалось отправить объявление {listing.url}. Оно не будет добавлено в историю сейчас.")
            except Exception as e:
                logger.exception(f"Ошибка при отправке объявления {listing.url}: {e}")

        # Обновляем историю
        if newly_sent_urls:
             updated_history = sent_urls_history.union(newly_sent_urls)
             save_sent_history(updated_history)
             logger.info(f"Обновлена история: добавлено {len(newly_sent_urls)} URL.")
        else:
             logger.info("История не обновлена.")

    logger.info("--- Основной цикл обработки завершен ---")

# --- Точка входа ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
         logger.info("Выполнение прервано пользователем.")
    except Exception as e:
        logger.critical(f"Критическая ошибка во время выполнения main_runner: {e}", exc_info=True)
        sys.exit(1) 