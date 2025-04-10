#!/usr/bin/env python3
"""
Скрипт для теста парсинга страницы деталей объявления с MercadoLibre.
"""

import asyncio
import os
import logging
import sys
import random
import json
from datetime import datetime
from pydantic import HttpUrl

from dotenv import load_dotenv

# --- ЯВНОЕ ДОБАВЛЕНИЕ КОРНЯ ПРОЕКТА В ПУТЬ ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ---------------------------------------------

# --- Настройка базового логгирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MLDetailTest")

# Устанавливаем уровень DEBUG для логгера парсера
logging.getLogger("parsers.mercadolibre").setLevel(logging.DEBUG)

# --- Загрузка конфигурации --- 
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, 'config', '.env'))

# --- Импорт компонентов приложения ---
try:
    from app.parsers.mercadolibre import MercadoLibreParser
    from app.models import Listing
    from playwright.async_api import async_playwright, Page

except ImportError as e:
    logger.error(f"IMPORT ERROR: {e}", exc_info=True)
    sys.exit(1)
except Exception as e:
    logger.error(f"UNEXPECTED ERROR DURING IMPORT: {e}", exc_info=True)
    sys.exit(1)

# --- URL страницы деталей для теста ---
TEST_DETAIL_URL = "https://terreno.mercadolibre.com.uy/MLU-707739404-barrio-abierto-en-ruta-21-los-ceibos-_JM"

# --- Основная асинхронная функция --- 
async def test_ml_detail_page():
    logger.info(f"--- Запуск теста парсинга ДЕТАЛЕЙ ({TEST_DETAIL_URL}) ---")
    
    # Создаем конфигурацию прокси 
    smartproxy_config = {
        "server": "uy.smartproxy.com:15001",
        "user_pattern": "spgai22txz",
        "password": os.getenv("SMARTPROXY_PASSWORD", "jtx6i24Jpb~eweNw2eo")
    }
    
    logger.info(f"Загружена конфигурация Smartproxy: сервер={smartproxy_config['server']}, пользователь={smartproxy_config['user_pattern']}")
    
    # Инициализируем парсер с конфигурацией прокси
    parser = MercadoLibreParser(smartproxy_config=smartproxy_config, headless_mode=False)
    logger.info(f"Парсер инициализирован с session_id: {parser.session_id}")
    
    context = None
    page = None
    updated_listing = None
    test_passed = False

    try:
        # Инициализация Playwright и браузера
        logger.info("Инициализация Playwright и браузера...")
        
        # Инициализация Playwright с новым методом
        browser_init_success = await parser._init_playwright(headless=False)
        if not browser_init_success:
            logger.error("Не удалось инициализировать Playwright")
            return False
        
        # Создаем страницу для теста
        page = await parser.context.new_page()
        
        if page:
            logger.info("Страница создана успешно")

        # 1. Переходим на страницу деталей объявления
        logger.info(f"Переход на страницу деталей: {TEST_DETAIL_URL}")
        await page.goto(TEST_DETAIL_URL, wait_until='load', timeout=60000)
        logger.info("Страница деталей загружена.")
        
        # Принять cookies (если есть)
        cookie_button_selector = 'button[data-testid="action:understood-button"]'
        try:
            logger.debug(f"Поиск кнопки cookies: {cookie_button_selector}")
            cookie_button = page.locator(cookie_button_selector).first
            await cookie_button.wait_for(state='visible', timeout=5000) # Ждем недолго
            logger.info("Кнопка cookies найдена, кликаем...")
            await cookie_button.click()
            await page.wait_for_timeout(500)
        except Exception:
            logger.info("Кнопка cookies не найдена или не кликнута (продолжаем)...")

        # 2. Создаем базовый объект Listing с URL и минимальными данными
        base_listing = Listing(
            url=TEST_DETAIL_URL,
            source=parser.SOURCE_NAME,
            title=None,
            price=None,
            location=None,
            area=None,
            image_url=None,
            description=None
        )
        
        # 3. Извлекаем данные со страницы деталей
        logger.info("Извлечение данных со страницы деталей...")
        updated_listing = await parser._extract_data_from_detail_page(page, base_listing)
        
        # Делаем скриншот для отладки
        debug_path = f"errors/detail_page_{random.randint(1000, 9999)}.png"
        await page.screenshot(path=debug_path)
        logger.info(f"Сохранен скриншот страницы деталей: {debug_path}")

        if not updated_listing:
            raise ValueError("Не удалось извлечь данные со страницы деталей (метод вернул None).")

        # 4. Сохраняем результаты в JSON для анализа
        logger.info(f"Данные извлечены успешно:")
        logger.info(f"  URL: {updated_listing.url}")
        logger.info(f"  Title: {updated_listing.title if updated_listing.title else 'Не найден'}")
        logger.info(f"  Price: {updated_listing.price if updated_listing.price else 'Не найдена'}")
        logger.info(f"  Location: {updated_listing.location if updated_listing.location else 'Не найдена'}")
        logger.info(f"  Area: {updated_listing.area if updated_listing.area else 'Не найдена'}")
        logger.info(f"  Image: {updated_listing.image_url if updated_listing.image_url else 'Не найден'}")
        logger.info(f"  Description: {(updated_listing.description[:50] + '...') if updated_listing.description else 'Не найдено'}")
        
        # Валидируем результаты
        if updated_listing.title and updated_listing.price:
            test_passed = True
            # Создаем директорию для результатов, если ее нет
            os.makedirs("test_results", exist_ok=True)
            # Сохраняем результаты в JSON
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result_path = f"test_results/ml_detailed_results_{timestamp}.json"
            
            # Преобразуем объект Listing в словарь для сериализации с обходом проблемных полей
            listing_dict = updated_listing.model_dump(exclude_none=True)
            # Создаем новый словарь с конвертированными значениями
            json_safe_dict = {}
            for key, value in listing_dict.items():
                # Преобразуем HttpUrl и подобные типы в строки
                if key == 'image_url' and value is not None:
                    json_safe_dict[key] = str(value)
                elif key == 'url' and value is not None:
                    json_safe_dict[key] = str(value)
                elif key in ['date_scraped', 'date_listed'] and value is not None:
                    # Преобразуем datetime в строку ISO формата
                    if hasattr(value, 'isoformat'):
                        json_safe_dict[key] = value.isoformat()
                    else:
                        json_safe_dict[key] = str(value)
                else:
                    json_safe_dict[key] = value
                
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(json_safe_dict, f, ensure_ascii=False, indent=2)
            logger.info(f"Результаты сохранены в {result_path}")

    except Exception as e:
        logger.error(f"ОШИБКА В ТЕСТЕ: {type(e).__name__} - {e}", exc_info=True)
        # Дополнительная диагностика
        if 'page' in locals() and page and not page.is_closed():
            try:
                error_content = await page.content()
                logger.debug(f"HTML страницы в момент ошибки: {error_content[:500]}...")  # Первые 500 символов
                
                # Сохраняем скриншот ошибки
                error_id = random.randint(1000, 9999)
                screenshot_path = f"errors/ml_detail_error_{error_id}.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"Скриншот ошибки сохранен: {screenshot_path}")
                
                # Сохраняем HTML страницы
                html_path = f"errors/ml_detail_error_{error_id}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(error_content)
                logger.info(f"HTML страницы сохранен: {html_path}")
            except Exception as screenshot_err:
                logger.error(f"Не удалось сохранить диагностическую информацию: {screenshot_err}")

    finally:
        logger.info("Завершение теста деталей, закрытие ресурсов...")
        # Используем метод парсера для закрытия ресурсов
        await parser._close_playwright()
        logger.info("Ресурсы Playwright закрыты.")

    if test_passed:
        logger.info("--- ТЕСТ ПАРСИНГА ДЕТАЛЕЙ ПРОЙДЕН УСПЕШНО --- ")
    else:
        logger.error("--- ТЕСТ ПАРСИНГА ДЕТАЛЕЙ НЕ ПРОЙДЕН --- ")

    return test_passed, updated_listing

# --- Точка входа ---
if __name__ == "__main__":
    logger.info("Запуск теста парсинга деталей объявления...")
    passed, _ = asyncio.run(test_ml_detail_page())
    sys.exit(0 if passed else 1) # Выход с кодом 0 если успех, 1 если ошибка 