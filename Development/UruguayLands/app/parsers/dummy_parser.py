#!/usr/bin/env python3
"""
Тестовый "заглушечный" парсер для проверки основного конвейера приложения.
"""

import logging
import asyncio
from typing import List, Optional
from datetime import datetime

from .base import BaseParser
from app.models import Listing

class DummyParser(BaseParser):
    """
    Простой парсер-заглушка.
    Не использует Playwright, просто возвращает тестовые данные.
    """
    SOURCE_NAME = "dummy"

    def __init__(self, proxy_list: Optional[List[str]] = None):
        # Вызываем init базового класса, но параметры request_delay и т.д. не важны
        super().__init__(proxy_list=proxy_list) 
        self.logger.info("Инициализирован DummyParser.")

    async def _get_page_url(self, page_number: int) -> str:
        # Этот метод не будет вызван в переопределенном run()
        return f"http://dummy-site.test/page={page_number}"

    async def _extract_listings_from_page(self, page) -> List[Listing]:
        # Этот метод не будет вызван в переопределенном run()
        # Возвращаем пустой список, чтобы соответствовать сигнатуре
        return []

    async def _extract_data_from_detail_page(self, page, listing: Listing) -> Optional[Listing]:
        """
        Пустая реализация для DummyParser.
        Этот метод не используется, так как run() переопределен.
        """
        self.logger.debug("Вызван _extract_data_from_detail_page в DummyParser (не используется)")
        # Просто возвращаем исходный листинг (или можно None)
        return listing

    async def run(self, max_pages: Optional[int] = None, headless: bool = True) -> List[Listing]:
        """
        Переопределенный метод run.
        Не запускает браузер, возвращает статические тестовые данные.
        """
        self.logger.info(f"--- Запуск DummyParser (режим заглушки) ---")
        self.stats['start_time'] = datetime.now()
        
        # Имитируем небольшую задержку
        await asyncio.sleep(1)

        # Создаем несколько тестовых объявлений
        test_listings_data = [
            {
                "title": "Тестовый Участок 1 Га",
                "price": "USD 10000",
                "location": "Тестовый Район, Тестовый Департамент",
                "area": "1 ha",
                "url": "http://dummy-site.test/listing/1",
                "source": self.SOURCE_NAME,
                "image_url": "https://via.placeholder.com/600x400.png?text=Test+Image+1",
                "description": "Это описание тестового участка номер 1."
            },
            {
                "title": "Другая Тестовая Chacra 5000 м²",
                "price": "U$S 5500",
                "location": "Где-то Еще, Другой Департамент",
                "area": "5000 m²",
                "url": "http://dummy-site.test/listing/2",
                "source": self.SOURCE_NAME,
                # Без картинки
                "description": "Второе тестовое объявление без картинки."
            },
            {
                 # Это объявление должно быть отфильтровано как уже существующее
                 # если мы добавим его URL в posted_listings.json или запустим второй раз
                "title": "Старое Тестовое Объявление",
                "price": "USD 1",
                "location": "Старое Место",
                "area": "1 m²",
                "url": "http://dummy-site.test/listing/OLD", 
                "source": self.SOURCE_NAME,
                "description": "Это объявление для проверки фильтрации."
            }
        ]

        results = []
        for data in test_listings_data:
             try:
                 results.append(Listing(**data))
             except Exception as e:
                 self.logger.error(f"Ошибка создания тестового Listing: {e} - Данные: {data}")

        self.stats['listings_found'] = len(results)
        self.stats['pages_processed'] = 1 # Имитируем обработку одной страницы
        self.stats['end_time'] = datetime.now()
        duration = self.stats['end_time'] - self.stats['start_time']
        self.logger.info(f"--- DummyParser завершен за {duration} ---")
        self.logger.info(f"Статистика: Найдено объявлений={self.stats['listings_found']}")

        return results 