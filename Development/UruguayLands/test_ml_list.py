#!/usr/bin/env python3
"""
Скрипт для теста парсинга страницы списка объявлений с MercadoLibre.
"""

import asyncio
import os
import logging
import sys
import random

from dotenv import load_dotenv

# --- ЯВНОЕ ДОБАВЛЕНИЕ КОРНЯ ПРОЕКТА В ПУТЬ ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ---------------------------------------------

# --- Настройка базового логгирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MLListTest")

# Устанавливаем уровень DEBUG для логгера парсера
logging.getLogger("parsers.mercadolibre").setLevel(logging.DEBUG)

# --- Загрузка конфигурации --- 
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, 'config', '.env'))

# --- Импорт компонентов приложения ---
try:
    from app.parsers.mercadolibre import MercadoLibreParser
    from app.models import Listing
    from playwright.async_api import async_playwright

except ImportError as e:
    logger.error(f"IMPORT ERROR: {e}", exc_info=True)
    sys.exit(1)
except Exception as e:
    logger.error(f"UNEXPECTED ERROR DURING IMPORT: {e}", exc_info=True)
    sys.exit(1)

# --- URL страницы списка для теста ---
TEST_LIST_URL = "https://listado.mercadolibre.com.uy/inmuebles/terrenos/venta/"

# --- Основная асинхронная функция --- 
async def test_ml_list_page():
    logger.info(f"--- Запуск теста парсинга СПИСКА ({TEST_LIST_URL}) ---")
    
    # Создаем конфигурацию прокси из переменных окружения или используем фиксированные значения
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
    listings = []
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

        # 1. Переходим на страницу списка объявлений
        logger.info(f"Переход на страницу списка: {TEST_LIST_URL}")
        await page.goto(TEST_LIST_URL, wait_until='load', timeout=60000)
        logger.info("Страница списка загружена.")
        
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

        # 2. Извлекаем данные со страницы списка
        logger.info("Извлечение списка объявлений...")
        listings = await parser._extract_listings_from_page(page)
        
        # Делаем скриншот для отладки
        debug_path = "errors/list_page_" + random.randint(1000, 9999).__str__() + ".png"
        await page.screenshot(path=debug_path)
        logger.info(f"Сохранен скриншот страницы списка: {debug_path}")

        if not listings or len(listings) == 0:
            raise ValueError("Не удалось извлечь объявления со страницы списка (метод вернул пустой список).")

        logger.info(f"Найдено {len(listings)} объявлений")
        for i, listing in enumerate(listings):
            logger.info(f"Объявление #{i+1}:")
            logger.info(f"  URL: {listing.url}")
            logger.info(f"  Title: {listing.title if listing.title else 'Не найден'}")
            logger.info(f"  Price: {listing.price if listing.price else 'Не найдена'}")
            logger.info(f"  Location: {listing.location if listing.location else 'Не найдена'}")
            logger.info(f"  Area: {listing.area if listing.area else 'Не найдена'}")
            logger.info(f"  Image: {listing.image_url if listing.image_url else 'Не найден'}")

        test_passed = len(listings) > 0

    except Exception as e:
        logger.error(f"ОШИБКА В ТЕСТЕ: {type(e).__name__} - {e}", exc_info=True)
        # Дополнительная диагностика
        if 'page' in locals() and page and not page.is_closed():
            try:
                error_content = await page.content()
                logger.debug(f"HTML страницы в момент ошибки: {error_content[:500]}...")  # Первые 500 символов
                
                # Сохраняем скриншот ошибки
                error_id = random.randint(1000, 9999)
                screenshot_path = f"errors/ml_list_error_{error_id}.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"Скриншот ошибки сохранен: {screenshot_path}")
                
                # Сохраняем HTML страницы
                html_path = f"errors/ml_list_error_{error_id}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(error_content)
                logger.info(f"HTML страницы сохранен: {html_path}")
            except Exception as screenshot_err:
                logger.error(f"Не удалось сохранить диагностическую информацию: {screenshot_err}")

    finally:
        logger.info("Завершение теста списка, закрытие ресурсов...")
        # Используем метод парсера для закрытия ресурсов
        await parser._close_playwright()
        logger.info("Ресурсы Playwright закрыты.")

    if test_passed:
        logger.info("--- ТЕСТ ПАРСИНГА СПИСКА ПРОЙДЕН УСПЕШНО --- ")
    else:
        logger.error("--- ТЕСТ ПАРСИНГА СПИСКА НЕ ПРОЙДЕН --- ")

    return test_passed

# --- Точка входа ---
if __name__ == "__main__":
    logger.info("Запуск теста парсинга списка объявлений...")
    passed = asyncio.run(test_ml_list_page())
    sys.exit(0 if passed else 1) # Выход с кодом 0 если успех, 1 если ошибка 