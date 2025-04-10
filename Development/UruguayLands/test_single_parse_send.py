#!/usr/bin/env python3
"""
Супер-упрощенный скрипт для теста парсинга ОДНОЙ страницы деталей
с MercadoLibre и отправки в Telegram.
"""

import asyncio
import os
import logging
import sys
import random
import json
from datetime import datetime

from dotenv import load_dotenv

# --- ЯВНОЕ ДОБАВЛЕНИЕ КОРНЯ ПРОЕКТА В ПУТЬ ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ---------------------------------------------

# --- Настройка базового логгирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MLParseAndSend")

# Устанавливаем уровень DEBUG для логгеров парсеров и Telegram
logging.getLogger("app.parsers.mercadolibre").setLevel(logging.DEBUG)
logging.getLogger("app.telegram_poster").setLevel(logging.DEBUG)

# --- Загрузка конфигурации --- 
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, 'config', '.env'))

# --- Импорт компонентов приложения ---
try:
    from app.parsers.mercadolibre import MercadoLibreParser
    from app.models import Listing
    from app.telegram_poster import post_to_telegram, send_telegram_sync
    from app.hashtag_generator import generate_hashtags
    from playwright.async_api import async_playwright, Error

except ImportError as e:
    logger.error(f"IMPORT ERROR: {e}", exc_info=True)
    sys.exit(1)
except Exception as e:
    logger.error(f"UNEXPECTED ERROR DURING IMPORT: {e}", exc_info=True)
    sys.exit(1)

# --- URL конкретного объявления для теста ---
# URL активного объявления с MercadoLibre Uruguay (terrenos/venta)
TEST_DETAIL_URL = "https://terreno.mercadolibre.com.uy/MLU-707739404-barrio-abierto-en-ruta-21-los-ceibos-_JM"

# --- Настройки теста ---
SEND_TO_TELEGRAM = True  # Включаем отправку в Telegram
USE_SYNC_SEND = False  # False - асинхронный send, True - синхронный send_telegram_sync

# --- Основная асинхронная функция --- 
async def ml_parse_and_send_test():
    logger.info(f"=== ЗАПУСК ПОЛНОГО ТЕСТА: ПАРСИНГ + ТЕЛЕГРАМ ===")
    logger.info(f"URL для теста: {TEST_DETAIL_URL}")
    logger.info(f"Отправка в Telegram: {'ВКЛЮЧЕНА' if SEND_TO_TELEGRAM else 'ВЫКЛЮЧЕНА'}")
    logger.info(f"Метод отправки: {'СИНХРОННЫЙ' if USE_SYNC_SEND else 'АСИНХРОННЫЙ'}")
    
    # Создаем конфигурацию прокси с новыми настройками
    smartproxy_config = {
        "server": "uy.smartproxy.com:15001",
        "user_pattern": "spgai22txz",
        "password": os.getenv("SMARTPROXY_PASSWORD", "jtx6i24Jpb~eweNw2eo")
    }
    
    logger.info(f"Загружена конфигурация Smartproxy: сервер={smartproxy_config['server']}, пользователь={smartproxy_config['user_pattern']}")
    
    # Инициализируем парсер с конфигурацией прокси
    parser = MercadoLibreParser(smartproxy_config=smartproxy_config, headless_mode=False)
    logger.info(f"Парсер инициализирован с session_id: {parser.session_id}")
    
    listing_to_send = None
    parse_success = False
    send_success = False
    telegam_result = False

    try:
        # 1. ЭТАП ПАРСИНГА: Используем метод _create_browser_context из BaseParser
        logger.info("Инициализация Playwright и браузера...")
        context = await parser._create_browser_context()
        if not context:
            raise Exception("Не удалось создать контекст браузера")
        
        # Проверяем IP адрес через прокси
        await parser._check_ip(context)
        
        # Создаем страницу из контекста
        page = await context.new_page()
        logger.info("Браузер и страница созданы.")

        # Переходим на страницу деталей объявления
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

        # Извлекаем данные со страницы деталей
        logger.info("Извлечение данных со страницы деталей...")
        
        # Создаем базовый объект Listing с минимальными данными
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
        
        # Извлекаем полные данные
        listing_to_send = await parser._extract_data_from_detail_page(page, base_listing)
        
        # Делаем скриншот для отладки
        debug_path = f"test_results/ml_page_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        os.makedirs("test_results", exist_ok=True)
        await page.screenshot(path=debug_path)
        logger.info(f"Сохранен скриншот страницы: {debug_path}")

        if not listing_to_send:
            raise ValueError("Не удалось извлечь данные со страницы (метод вернул None).")

        parse_success = True
        
        # Выводим полученные данные
        logger.info("=== ДАННЫЕ ИЗВЛЕЧЕНЫ УСПЕШНО ===")
        logger.info(f"  URL: {listing_to_send.url}")
        logger.info(f"  Title: {listing_to_send.title}")
        logger.info(f"  Price: {listing_to_send.price}")
        logger.info(f"  Location: {listing_to_send.location}")
        logger.info(f"  Area: {listing_to_send.area}")
        logger.info(f"  Image: {listing_to_send.image_url}")
        
        # Выводим часть описания (может быть длинным)
        description_text = listing_to_send.description[:100] + "..." if listing_to_send.description else "Отсутствует"
        logger.info(f"  Description: {description_text}")
        
        # 2. ЗАКРЫВАЕМ РЕСУРСЫ PLAYWRIGHT ПЕРЕД ОТПРАВКОЙ В TELEGRAM
        # Это решает часть проблем с сетевыми конфликтами (см. progress.txt)
        logger.info("Закрываем ресурсы Playwright перед отправкой в Telegram...")
        await parser._close_playwright()
        logger.info("Ресурсы Playwright закрыты.")
        
        # Пауза для освобождения сетевых ресурсов
        await asyncio.sleep(1)
        
        # 3. ЭТАП ОТПРАВКИ В TELEGRAM
        if SEND_TO_TELEGRAM and listing_to_send:
            # Преобразуем Pydantic объект в словарь и обрабатываем проблемные типы
            listing_dict = listing_to_send.model_dump()
            
            # 1. Обрабатываем URL (HttpUrl -> str)
            if 'url' in listing_dict:
                listing_dict['url'] = str(listing_dict['url'])
                
            # 2. Обрабатываем image_url (HttpUrl -> str или None)
            if 'image_url' in listing_dict and listing_dict['image_url'] is not None:
                listing_dict['image_url'] = str(listing_dict['image_url'])
                
            # 3. Обрабатываем datetime (datetime -> str)
            if 'date_scraped' in listing_dict and listing_dict['date_scraped'] is not None:
                if hasattr(listing_dict['date_scraped'], 'isoformat'):
                    listing_dict['date_scraped'] = listing_dict['date_scraped'].isoformat()
                    
            # 4. Генерируем хештеги
            try:
                listing_dict['hashtags'] = generate_hashtags(listing_dict)
                logger.info(f"Сгенерированы хештеги: {listing_dict['hashtags']}")
            except Exception as e:
                logger.warning(f"Ошибка при генерации хештегов: {e}")
                listing_dict['hashtags'] = []
                
            # Сохраняем данные в JSON для отладки
            json_path = f"test_results/ml_telegram_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(listing_dict, f, ensure_ascii=False, indent=2)
            logger.info(f"Данные для Telegram сохранены в {json_path}")
            
            # Выбираем метод отправки (синхронный или асинхронный)
            logger.info(f"Отправка объявления в Telegram {'(СИНХРОННО)' if USE_SYNC_SEND else '(АСИНХРОННО)'}...")
            
            if USE_SYNC_SEND:
                # Синхронный метод (через requests напрямую в API)
                telegam_result = send_telegram_sync(listing_dict)
            else:
                # Асинхронный метод (через python-telegram-bot)
                telegam_result = await post_to_telegram(listing_dict)
                
            if telegam_result:
                logger.info("✅ Объявление успешно отправлено в Telegram!")
                send_success = True
            else:
                logger.error("❌ Не удалось отправить объявление в Telegram.")
        else:
            logger.info("Отправка в Telegram пропущена.")
            send_success = True  # Считаем успешным, если отправка не требовалась

    except Exception as e:
        logger.error(f"ОШИБКА В ТЕСТЕ: {type(e).__name__} - {e}", exc_info=True)
        # Дополнительная диагностика
        if 'page' in locals() and page and not page.is_closed():
            try:
                error_content = await page.content()
                logger.debug(f"HTML страницы в момент ошибки: {error_content[:500]}...")  # Первые 500 символов
                
                # Сохраняем скриншот ошибки
                error_id = random.randint(1000, 9999)
                screenshot_path = f"test_results/ml_error_{error_id}.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"Скриншот ошибки сохранен: {screenshot_path}")
                
                # Сохраняем HTML страницы
                html_path = f"test_results/ml_error_{error_id}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(error_content)
                logger.info(f"HTML страницы сохранен: {html_path}")
            except Exception as screenshot_err:
                logger.error(f"Не удалось сохранить диагностическую информацию: {screenshot_err}")

    finally:
        # Закрываем ресурсы Playwright, если они ещё не закрыты
        if 'parser' in locals() and hasattr(parser, '_close_playwright'):
            try:
                await parser._close_playwright()
                logger.info("Ресурсы Playwright закрыты (finally).")
            except:
                pass

    # Итоговый результат
    if parse_success:
        logger.info("✅ ПАРСИНГ: успешно")
    else:
        logger.error("❌ ПАРСИНГ: не удался")
        
    if SEND_TO_TELEGRAM:
        if send_success:
            logger.info("✅ TELEGRAM: отправлено успешно")
        else:
            logger.error("❌ TELEGRAM: отправка не удалась")
    else:
        logger.info("➖ TELEGRAM: отправка не выполнялась")
        
    return parse_success and (send_success if SEND_TO_TELEGRAM else True)

# --- Точка входа ---
if __name__ == "__main__":
    logger.info("Запуск теста: парсинг MercadoLibre + отправка в Telegram...")
    success = asyncio.run(ml_parse_and_send_test())
    sys.exit(0 if success else 1) # Выход с кодом 0 если успех, 1 если ошибка 