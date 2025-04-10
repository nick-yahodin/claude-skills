#!/usr/bin/env python3
"""
Базовый класс для парсеров недвижимости.
"""

import asyncio
import logging
import random
import os
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import stealth_async

# Импортируем модель данных
from app.models import Listing

class BaseParser(ABC):
    """
    Абстрактный базовый класс для всех парсеров.
    Определяет интерфейс и базовую функциональность для работы с браузером.
    """
    SOURCE_NAME: str = "base"  # Должен быть переопределен в дочерних классах

    def __init__(self, 
                 max_retries: int = 3, 
                 request_delay: tuple = (2, 5),
                 headless_mode: bool = True):
        """
        Инициализирует парсер.
        
        Args:
            max_retries: Максимальное количество попыток при ошибке
            request_delay: Диапазон задержки между запросами в секундах (мин, макс)
            headless_mode: Запускать браузер в фоновом режиме без GUI
        """
        self.logger = logging.getLogger(f"parsers.{self.SOURCE_NAME}")
        self.max_retries = max_retries
        self.headless_mode = headless_mode
        self.request_delay_min, self.request_delay_max = request_delay
        
        # Playwright-ресурсы
        self.browser = None
        self.context = None
        
        # Для отслеживания обработанных URL
        self.seen_urls: Set[str] = set()
        
        # Статистика
        self.stats = {
            "pages_processed": 0,
            "listings_found": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None
        }

    async def _init_browser(self) -> bool:
        """
        Инициализирует браузер Playwright.
        
        Returns:
            bool: True если инициализация прошла успешно
        """
        try:
            self.logger.info(f"Инициализация браузера (headless={self.headless_mode})")
            
            # Запускаем Playwright
            playwright = await async_playwright().start()
            
            # Запуск браузера
            self.browser = await playwright.chromium.launch(
                headless=self.headless_mode
            )
            
            # Создаем контекст с размером окна
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            
            # Применяем stealth.js для маскировки автоматизации
            page = await self.context.new_page()
            await stealth_async(page)
            await page.close()
            
            self.logger.info("Браузер успешно инициализирован")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации браузера: {e}")
            await self.close()
            return False

    async def _page_navigation(self, page: Page, url: str) -> bool:
        """
        Выполняет навигацию на указанный URL с обработкой ошибок.
        
        Args:
            page: Страница браузера
            url: URL для загрузки
            
        Returns:
            bool: True если навигация успешна
        """
        for attempt in range(self.max_retries):
            try:
                self.logger.debug(f"Переход на URL (попытка {attempt+1}/{self.max_retries}): {url}")
                
                response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                if response and response.ok:
                    self.logger.debug(f"Страница успешно загружена: {url}")
                    return True
                else:
                    status = response.status if response else "нет ответа"
                    self.logger.warning(f"Ошибка загрузки страницы: {status}")
                    
                    if attempt < self.max_retries - 1:
                        retry_delay = 3 * (attempt + 1)
                        self.logger.debug(f"Повторная попытка через {retry_delay} сек...")
                        await asyncio.sleep(retry_delay)
                    
            except Exception as e:
                self.logger.warning(f"Ошибка при загрузке {url}: {e}")
                
                if attempt < self.max_retries - 1:
                    retry_delay = 3 * (attempt + 1)
                    self.logger.debug(f"Повторная попытка через {retry_delay} сек...")
                    await asyncio.sleep(retry_delay)
                else:
                    self.logger.error(f"Не удалось загрузить {url} после {self.max_retries} попыток")
                    return False
        
        return False

    async def _delay(self):
        """Выполняет случайную задержку между запросами."""
        secs = random.uniform(self.request_delay_min, self.request_delay_max)
        await asyncio.sleep(secs)

    async def close(self):
        """Освобождает ресурсы браузера."""
        if self.context:
            try:
                await self.context.close()
            except Exception as e:
                self.logger.error(f"Ошибка при закрытии контекста: {e}")
            finally:
                self.context = None
                
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                self.logger.error(f"Ошибка при закрытии браузера: {e}")
            finally:
                self.browser = None

    @abstractmethod
    async def _get_page_url(self, page_number: int) -> str:
        """
        Возвращает URL страницы поиска с учетом номера страницы.
        
        Args:
            page_number: Номер страницы (начиная с 1)
            
        Returns:
            str: URL страницы поиска
        """
        pass

    @abstractmethod
    async def _extract_listings_from_page(self, page: Page) -> List[Listing]:
        """
        Извлекает объявления со страницы поиска.
        
        Args:
            page: Объект страницы браузера
            
        Returns:
            List[Listing]: Список объявлений
        """
        pass

    async def run(self, max_pages: Optional[int] = None, headless: bool = True) -> List[Listing]:
        """
        Основной метод запуска парсера.
        
        Args:
            max_pages: Максимальное количество страниц для обработки
            headless: Запускать браузер в фоновом режиме
            
        Returns:
            List[Listing]: Список объявлений
        """
        if max_pages is None:
            max_pages = int(os.getenv("MAX_PAGES", "2"))
            
        self.headless_mode = headless
        self.stats['start_time'] = datetime.now()
        all_listings: List[Listing] = []
        
        self.logger.info(f"Запуск парсера {self.SOURCE_NAME} (макс. страниц: {max_pages})")
        
        try:
            # Инициализация браузера
            if not await self._init_browser():
                self.logger.error("Не удалось инициализировать браузер")
                return []
            
            # Обработка страниц
            for page_number in range(1, max_pages + 1):
                try:
                    # Получаем URL текущей страницы
                    page_url = await self._get_page_url(page_number)
                    self.logger.info(f"Обработка страницы {page_number}/{max_pages}: {page_url}")
                    
                    # Создаем новую страницу
                    browser_page = await self.context.new_page()
                    
                    # Переходим на страницу
                    if not await self._page_navigation(browser_page, page_url):
                        self.logger.warning(f"Пропуск страницы {page_number} из-за ошибки навигации")
                        await browser_page.close()
                        continue
                    
                    # Извлекаем объявления с текущей страницы
                    try:
                        page_listings = await self._extract_listings_from_page(browser_page)
                        self.logger.info(f"Найдено {len(page_listings)} объявлений на странице {page_number}")
                        all_listings.extend(page_listings)
                        self.stats["pages_processed"] += 1
                    except Exception as e:
                        self.logger.error(f"Ошибка при извлечении объявлений: {e}")
                        self.stats["errors"] += 1
                    
                    # Закрываем страницу
                    await browser_page.close()
                    
                    # Делаем задержку перед следующей страницей
                    if page_number < max_pages:
                        await self._delay()
                        
                except Exception as page_error:
                    self.logger.error(f"Ошибка при обработке страницы {page_number}: {page_error}")
                    self.stats["errors"] += 1
            
            # Удаляем дубликаты
            unique_listings = self._remove_duplicates(all_listings)
            
            self.stats["listings_found"] = len(unique_listings)
            self.stats["end_time"] = datetime.now()
            
            self.logger.info(f"Парсер {self.SOURCE_NAME} завершил работу. "
                           f"Обработано страниц: {self.stats['pages_processed']}, "
                           f"найдено объявлений: {self.stats['listings_found']}")
            
            return unique_listings
            
        except Exception as e:
            self.logger.error(f"Критическая ошибка в парсере {self.SOURCE_NAME}: {e}")
            traceback.print_exc()
            return []
            
        finally:
            # Освобождаем ресурсы
            await self.close()

    def _remove_duplicates(self, listings: List[Listing]) -> List[Listing]:
        """
        Удаляет дубликаты объявлений по URL.
        
        Args:
            listings: Список объявлений
            
        Returns:
            List[Listing]: Список уникальных объявлений
        """
        seen_urls = set()
        unique_listings = []
        
        for listing in listings:
            url = str(listing.url)
            if url not in seen_urls:
                seen_urls.add(url)
                unique_listings.append(listing)
        
        return unique_listings

    def now_utc(self) -> datetime:
        """Возвращает текущее время в UTC."""
        return datetime.now(timezone.utc) 