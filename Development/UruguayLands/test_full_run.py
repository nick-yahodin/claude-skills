#!/usr/bin/env python3
"""
Скрипт для полного запуска парсера MercadoLibre и тестирования извлечения данных
"""

import asyncio
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import List

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("full_test")

# Импортируем парсер
from app.parsers.mercadolibre import MercadoLibreParser
from app.models import Listing

async def save_results(listings: List[Listing], filename: str):
    """Сохраняет результаты в JSON-файл."""
    results_dir = Path(__file__).parent / "test_results"
    results_dir.mkdir(exist_ok=True)
    
    file_path = results_dir / filename
    
    # Преобразуем Listing объекты в словари
    listings_data = []
    for listing in listings:
        listing_dict = listing.model_dump()
        # Убедимся, что URL правильно преобразован в строку
        listing_dict["url"] = str(listing_dict["url"])
        # То же для image_url, если есть
        if listing_dict.get("image_url"):
            listing_dict["image_url"] = str(listing_dict["image_url"])
        # Преобразуем datetime объекты в строки
        if listing_dict.get("date_scraped"):
            listing_dict["date_scraped"] = listing_dict["date_scraped"].isoformat()
        if listing_dict.get("date_added"):
            listing_dict["date_added"] = listing_dict["date_added"].isoformat()
        if listing_dict.get("date_updated"):
            listing_dict["date_updated"] = listing_dict["date_updated"].isoformat()
        listings_data.append(listing_dict)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(listings_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Результаты сохранены в {file_path}")

async def run_test():
    """Запуск полного теста парсера."""
    logger.info("Начало полного теста парсера MercadoLibre")
    
    try:
        # Инициализация парсера
        parser = MercadoLibreParser()
        
        # Параметры запуска
        max_pages = 1  # Количество страниц для обработки
        headless = True  # Запуск браузера в фоновом режиме
        detail_processing = True # Включаем обратно обработку деталей
        
        logger.info(f"Запуск парсера с параметрами: max_pages={max_pages}, headless={headless}, detail_processing={detail_processing}")
        
        # Запуск парсера
        start_time = datetime.now()
        listings = await parser.run(max_pages=max_pages, headless=headless, detail_processing=detail_processing)
        end_time = datetime.now()
        
        # Расчет времени выполнения
        elapsed_time = (end_time - start_time).total_seconds()
        
        logger.info(f"Парсер завершил работу. Время выполнения: {elapsed_time:.2f} секунд.")
        logger.info(f"Извлечено объявлений: {len(listings)}")
        
        # Сохранение результатов (оставляем, может быть полезно)
        if listings:
             timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
             await save_results(listings, f"ml_full_run_{timestamp}.json")
        
    except Exception as e:
        logger.error(f"Ошибка при запуске парсера: {e}", exc_info=True)
    
    logger.info("Тест завершен")

if __name__ == "__main__":
    asyncio.run(run_test()) 