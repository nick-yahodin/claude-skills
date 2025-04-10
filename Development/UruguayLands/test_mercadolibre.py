#!/usr/bin/env python3
"""
Тестовый скрипт для парсера MercadoLibre с пошаговым логированием результатов.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mercadolibre_test")

# Добавляем корневую директорию проекта в sys.path
import sys
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Загружаем переменные окружения
from dotenv import load_dotenv
dotenv_path = PROJECT_ROOT / 'config' / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
    logger.info(f"Переменные окружения загружены из {dotenv_path}")
else:
    logger.warning(f"Файл .env не найден в {dotenv_path}")

# Импортируем парсер
from app.parsers.mercadolibre import MercadoLibreParser
from app.models import Listing

# Настройки теста
MAX_CARDS_TO_PROCESS = 5  # Увеличим количество карточек для более полного тестирования
MAX_PAGES = 1
SAVE_RESULTS = True
HEADLESS_MODE = True  # True для фонового режима, False для отображения браузера
VERBOSE_OUTPUT = True  # Подробный вывод деталей для каждой карточки

async def save_results(listings: List[Listing], filename: str):
    """Сохраняет результаты в JSON-файл."""
    results_dir = PROJECT_ROOT / "test_results"
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

async def test_list_page_parsing():
    """Тестирует парсинг страницы списка объявлений."""
    logger.info("=== Тестирование парсинга списка объявлений ===")
    
    # Инициализация парсера
    parser = MercadoLibreParser()
    
    try:
        # Создание Playwright и контекста
        await parser._init_playwright(headless=HEADLESS_MODE)
        parser.context = await parser._create_context()
        
        # Создание страницы
        page = await parser.context.new_page()
        
        # Получение URL первой страницы
        url = await parser._get_page_url(1)
        logger.info(f"URL страницы списка: {url}")
        
        # Переход на страницу
        try:
            logger.info("Переход на страницу списка...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            logger.info("Страница списка загружена успешно")
            
            # Делаем скриншот для анализа
            screenshot_path = PROJECT_ROOT / "test_results" / "ml_list_page.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            logger.info(f"Скриншот сохранен: {screenshot_path}")
            
            # Извлекаем HTML для анализа
            html_content = await page.content()
            html_path = PROJECT_ROOT / "test_results" / "ml_page_source.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"HTML-код страницы сохранен в {html_path}")
            
            # Анализ структуры страницы
            logger.info("=== Анализ структуры страницы ===")
            
            # Проверяем наличие контейнера списка
            container_selector = parser.list_selectors['container']
            container = await page.query_selector(container_selector)
            if container:
                logger.info(f"Контейнер списка найден: {container_selector}")
            else:
                logger.warning(f"Контейнер списка НЕ найден: {container_selector}")
                
                # Пробуем альтернативные селекторы
                alt_container_selectors = [
                    "div.ui-search-results", 
                    "section.ui-search-results", 
                    "div.ui-search-layout",
                    "div.shops__result-content",
                    "div.ui-search-main"
                ]
                for alt_selector in alt_container_selectors:
                    alt_container = await page.query_selector(alt_selector)
                    if alt_container:
                        logger.info(f"Найден альтернативный контейнер: {alt_selector}")
                    else:
                        logger.debug(f"Альтернативный контейнер не найден: {alt_selector}")
            
            # Поиск карточек товаров
            card_selector = parser.list_selectors['item']
            cards = await page.query_selector_all(card_selector)
            if cards:
                logger.info(f"Найдено {len(cards)} карточек по селектору: {card_selector}")
                
                # Проверяем первую карточку на наличие ссылки
                if len(cards) > 0:
                    first_card = cards[0]
                    logger.info("=== Проверка селекторов для первой карточки ===")
                    
                    # Извлекаем HTML первой карточки для анализа
                    card_html = await page.evaluate('(element) => element.outerHTML', first_card)
                    card_html_path = PROJECT_ROOT / "test_results" / "ml_first_card.html"
                    with open(card_html_path, "w", encoding="utf-8") as f:
                        f.write(card_html)
                    logger.info(f"HTML первой карточки сохранен в {card_html_path}")
                    
                    # Проверка основных селекторов первой карточки
                    for selector_name, selector in parser.list_selectors.items():
                        if isinstance(selector, str) and selector_name not in ['container', 'item']:
                            element = await first_card.query_selector(selector)
                            if element:
                                if selector_name == 'url':
                                    value = await element.get_attribute("href")
                                    logger.info(f"Селектор '{selector_name}': '{selector}' => {value}")
                                elif selector_name == 'image':
                                    src = await element.get_attribute("src")
                                    logger.info(f"Селектор '{selector_name}': '{selector}' => {src}")
                                else:
                                    text = await element.text_content()
                                    logger.info(f"Селектор '{selector_name}': '{selector}' => {text.strip()}")
                            else:
                                logger.warning(f"Элемент не найден по селектору '{selector_name}': '{selector}'")
            else:
                logger.warning(f"Карточки не найдены по селектору: {card_selector}")
            
            # Ограничение количества карточек для обработки
            original_extract_listings = parser._extract_listings_from_page
            
            async def limited_extract_listings(page):
                # Оригинальный метод, но с ограничением количества карточек
                listings = await original_extract_listings(page)
                if MAX_CARDS_TO_PROCESS > 0 and len(listings) > MAX_CARDS_TO_PROCESS:
                    logger.info(f"Ограничение результатов до {MAX_CARDS_TO_PROCESS} карточек (было {len(listings)})")
                    return listings[:MAX_CARDS_TO_PROCESS]
                return listings
            
            # Временно заменяем метод
            parser._extract_listings_from_page = limited_extract_listings
            
            # Парсинг страницы списка
            logger.info("Запуск парсинга списка...")
            listings = await parser._extract_listings_from_page(page)
            logger.info(f"Парсинг списка завершен. Найдено {len(listings)} объявлений.")
            
            if not listings:
                logger.error("Не найдено ни одного объявления! Проверьте селекторы и структуру страницы.")
                return
            
            # Выводим информацию о найденных объявлениях
            for i, listing in enumerate(listings):
                logger.info(f"--- Объявление {i+1}/{len(listings)} ---")
                logger.info(f"URL: {listing.url}")
                logger.info(f"Заголовок: {listing.title}")
                logger.info(f"Цена: {listing.price}")
                logger.info(f"Локация: {listing.location}")
                logger.info(f"Площадь: {listing.area}")
                logger.info(f"Изображение: {listing.image_url}")
            
            # Сохранение результатов
            if SAVE_RESULTS:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                await save_results(listings, f"ml_list_results_{timestamp}.json")
            
            # Парсинг детальных страниц
            logger.info("=== Тестирование парсинга детальных страниц ===")
            for i, listing in enumerate(listings):
                if i >= MAX_CARDS_TO_PROCESS:
                    break
                
                logger.info(f"Парсинг деталей для объявления {i+1}/{len(listings)}: {listing.url}")
                
                try:
                    # Переход на страницу объявления
                    await page.goto(str(listing.url), wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    
                    # Скриншот страницы деталей
                    screenshot_path = PROJECT_ROOT / "test_results" / f"ml_detail_{i+1}.png"
                    await page.screenshot(path=screenshot_path, full_page=True)
                    logger.info(f"Скриншот детальной страницы {i+1} сохранен: {screenshot_path}")
                    
                    # Получение деталей
                    updated_listing = await parser._extract_data_from_detail_page(page, listing)
                    logger.info(f"Детали для объявления {i+1} получены")
                    
                    # Выводим обновленную информацию
                    logger.info(f"--- Обновленные данные для объявления {i+1} ---")
                    logger.info(f"URL: {updated_listing.url}")
                    logger.info(f"Заголовок: {updated_listing.title}")
                    logger.info(f"Цена: {updated_listing.price}")
                    logger.info(f"Локация: {updated_listing.location}")
                    logger.info(f"Площадь: {updated_listing.area}")
                    logger.info(f"Изображение: {updated_listing.image_url}")
                    if updated_listing.description:
                        logger.info(f"Описание (первые 100 символов): {updated_listing.description[:100]}...")
                    if updated_listing.utilities:
                        logger.info(f"Характеристики: {updated_listing.utilities}")
                except Exception as e:
                    logger.error(f"Ошибка при парсинге деталей для {listing.url}: {e}", exc_info=True)
            
            # Сохранение результатов с деталями
            if SAVE_RESULTS:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                await save_results(listings, f"ml_detailed_results_{timestamp}.json")
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке страницы списка: {e}", exc_info=True)
    
    except Exception as e:
        logger.error(f"Ошибка при инициализации парсера: {e}", exc_info=True)
    
    finally:
        # Закрытие ресурсов
        logger.info("Закрытие ресурсов парсера...")
        await parser._close_playwright()
        logger.info("Ресурсы закрыты")

async def test_full_parser_run():
    """Тестирует полный запуск парсера."""
    logger.info("=== Тестирование полного запуска парсера ===")
    
    parser = MercadoLibreParser()
    
    try:
        # Запуск парсера с ограничением количества страниц
        logger.info(f"Запуск парсера (max_pages={MAX_PAGES}, headless={HEADLESS_MODE})...")
        listings = await parser.run(max_pages=MAX_PAGES, headless=HEADLESS_MODE, detail_processing=True)
        
        logger.info(f"Парсер завершил работу. Найдено {len(listings)} объявлений.")
        
        # Выводим информацию о найденных объявлениях
        for i, listing in enumerate(listings[:MAX_CARDS_TO_PROCESS]):  # Выводим только первые MAX_CARDS_TO_PROCESS
            logger.info(f"--- Объявление {i+1}/{min(len(listings), MAX_CARDS_TO_PROCESS)} ---")
            logger.info(f"URL: {listing.url}")
            logger.info(f"Заголовок: {listing.title}")
            logger.info(f"Цена: {listing.price}")
            logger.info(f"Локация: {listing.location}")
            logger.info(f"Площадь: {listing.area}")
            logger.info(f"Изображение: {listing.image_url}")
            if listing.description and VERBOSE_OUTPUT:
                logger.info(f"Описание (первые 100 символов): {listing.description[:100]}...")
            if listing.utilities and VERBOSE_OUTPUT:
                logger.info(f"Характеристики: {listing.utilities}")
        
        # Сохранение результатов
        if SAVE_RESULTS and listings:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            await save_results(listings, f"ml_full_run_{timestamp}.json")
    
    except Exception as e:
        logger.error(f"Ошибка при запуске парсера: {e}", exc_info=True)

async def main():
    """Основная функция для тестирования."""
    logger.info("Начало тестирования парсера MercadoLibre")
    
    # Тест парсинга страницы списка и детальных страниц
    await test_list_page_parsing()
    
    # Тест полного запуска парсера
    # await test_full_parser_run()
    
    logger.info("Тестирование завершено")

if __name__ == "__main__":
    asyncio.run(main()) 