#!/usr/bin/env python3
"""
Тестирование парсера MercadoLibre на нескольких объявлениях.
"""

import os
import sys
import json
import logging
import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Добавляем путь к корневой директории проекта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Импортируем парсер и модели
from app.parsers.mercadolibre import MercadoLibreParser
from app.models import Listing
try:
    # Импортируем функции из telegram_poster
    from app.telegram_poster import send_telegram_sync
    from app.telegram_poster import send_telegram_message_async
    from app.hashtag_generator import generate_hashtags
except ImportError as e:
    logger.warning(f"Ошибка импорта: {e}")
    
    # Функция-заглушка для отправки через Telegram (синхронно)
    def send_telegram_sync(listing):
        logger.warning("Функция send_telegram_sync не найдена, используется заглушка")
        print(f"Отправка в Telegram (синхронно): {listing.get('title')}")
        return True
    
    # Функция-заглушка для отправки через Telegram (асинхронно)
    async def send_telegram_message_async(listing):
        logger.warning("Функция send_telegram_message_async не найдена, используется заглушка")
        print(f"Отправка в Telegram (асинхронно): {listing.get('title')}")
        return True

    # Если модуль generate_hashtags отсутствует, используем заглушку
    def generate_hashtags(listing: Dict[str, Any]) -> List[str]:
        """Простая заглушка для генерации хэштегов если модуль не найден."""
        logger.warning("Модуль app.hashtag_generator не найден, используется заглушка")
        hashtags = ["#Uruguay", "#TerrenosUY"]
        
        # Добавляем хэштег источника
        if listing.get("source"):
            hashtags.append(f"#{listing['source'].capitalize()}")
        
        # Добавляем хэштег площади
        area = listing.get("area", "")
        if "hectárea" in area or "ha" in area:
            hashtags.append("#Hectáreas")
        elif "m²" in area or "m2" in area:
            hashtags.append("#MetrosCuadrados")
            
        # Добавляем хэштег локации
        location = listing.get("location", "")
        if "montevideo" in location.lower():
            hashtags.append("#Montevideo")
        elif "maldonado" in location.lower():
            hashtags.append("#Maldonado")
        elif "canelones" in location.lower():
            hashtags.append("#Canelones")
        else:
            hashtags.append("#OtrosDepartamentos")
            
        return hashtags

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MLMultipleTest')

# Стартовые URL для тестирования
TEST_URLS = [
    "https://articulo.mercadolibre.com.uy/MLU-688357290-venta-terreno-punta-del-este-braglia-1691-_JM", 
    "https://terreno.mercadolibre.com.uy/MLU-795629242-terreno-aguas-dulces-a-2-cuadras-del-mar-_JM",
    "https://terreno.mercadolibre.com.uy/MLU-832166343-terreno-en-montevideo-_JM",
    "https://terreno.mercadolibre.com.uy/MLU-812861713-lindo-terreno-sobre-ruta-39-tala-canelones-_JM",
    "https://terreno.mercadolibre.com.uy/MLU-849166752-terreno-50000m-avenida-san-martin-_JM"
]

# Настройки отправки в Telegram
SEND_TO_TELEGRAM = True  # True - отправлять в Telegram, False - только парсить
USE_SYNC_SEND = False    # False - асинхронный API, True - синхронный API через requests
DELAY_BETWEEN_SENDS = 3  # Задержка между отправками в секундах
DEBUG_MODE = True        # True - показывать браузер, False - скрытый режим (headless)

# --- Вспомогательные функции ---
async def handle_single_listing(idx, url, smartproxy_config, stats):
    """Обрабатывает одно объявление: парсит детали, отправляет в Telegram."""
    logger = logging.getLogger('MLMultipleTest')
    
    try:
        logger.info(f"=== ОБЪЯВЛЕНИЕ {idx+1}/{len(TEST_URLS)}: {url} ===")
        logger.info(f"[{idx+1}] Инициализация браузера и создание контекста...")
        
        # Инициализируем парсер с конфигурацией прокси для каждого объявления
        # Это гарантирует чистый контекст для каждого теста
        parser = MercadoLibreParser(smartproxy_config=smartproxy_config, headless_mode=not DEBUG_MODE)
        
        # Обработка одного объявления
        try:
            # 1. Создание браузера и страницы
            context = await parser._create_browser_context()
            if not context:
                raise Exception(f"[{idx+1}] Не удалось создать контекст браузера")
                
            # Проверка IP
            await parser._check_ip(context)
            page = await context.new_page()
            logger.info(f"[{idx+1}] Браузер и страница созданы.")
            
            # 2. Загрузка страницы
            logger.info(f"[{idx+1}] Загрузка страницы: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            logger.info(f"[{idx+1}] Страница загружена.")
            
            # 3. Принятие cookies (если нужно)
            logger.info(f"[{idx+1}] Принятие cookies...")
            try:
                accept_btn = page.locator('button:has-text("Aceptar"), button:has-text("Accept")')
                if await accept_btn.count() > 0:
                    await accept_btn.first.click()
                    await page.wait_for_timeout(1000)
            except Exception as cookie_err:
                logger.warning(f"[{idx+1}] Ошибка при принятии cookies: {cookie_err}")
            
            # 4. Создание объекта Listing и извлечение данных
            logger.info(f"[{idx+1}] Извлечение данных...")
            listing = Listing(url=url, source=parser.SOURCE_NAME)
            updated_listing = await parser._extract_data_from_detail_page(page, listing)
            
            # 5. Сохранение скриншота
            debug_dir = "test_results"
            os.makedirs(debug_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%H%M%S")
            screenshot_path = f"{debug_dir}/ml_obj{idx+1}_{timestamp}.png"
            await page.screenshot(path=screenshot_path)
            logger.info(f"[{idx+1}] Скриншот сохранен: {screenshot_path}")
            
            # 6. Обработка результатов
            if updated_listing:
                logger.info(f"[{idx+1}] Данные успешно извлечены:")
                logger.info(f"[{idx+1}] - Заголовок: {updated_listing.title}")
                logger.info(f"[{idx+1}] - Цена: {updated_listing.price}")
                logger.info(f"[{idx+1}] - Локация: {updated_listing.location}")
                logger.info(f"[{idx+1}] - Площадь: {updated_listing.area}")
                logger.info(f"[{idx+1}] - Фото: {updated_listing.image_url}")
                if updated_listing.description:
                    logger.info(f"[{idx+1}] - Описание: {updated_listing.description[:70]}...")
                
                # 7. Закрытие ресурсов Playwright
                logger.info(f"[{idx+1}] Закрытие ресурсов Playwright...")
                await parser._close_playwright()
                logger.info(f"[{idx+1}] Ресурсы Playwright закрыты.")
                
                # 8. Добавление хэштегов
                await asyncio.sleep(1)  # Небольшая пауза для стабильности
                updated_dict = updated_listing.model_dump()
                try:
                    hash_tags = generate_hashtags(updated_dict)
                    updated_dict['hashtags'] = hash_tags
                    logger.info(f"[{idx+1}] Сгенерированы хештеги: {hash_tags}")
                except:
                    updated_dict['hashtags'] = []
                    logger.warning(f"[{idx+1}] Не удалось сгенерировать хештеги")
                
                # 9. Сохранение данных в файл для отладки
                json_path = f"{debug_dir}/ml_obj{idx+1}_data_{timestamp}.json"
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(updated_dict, f, ensure_ascii=False, indent=2)
                logger.info(f"Данные сохранены в {json_path}")
                
                # 10. Отправка в Telegram (если включено)
                if SEND_TO_TELEGRAM:
                    logger.info(f"[{idx+1}] Отправка в Telegram ({'АСИНХРОННО' if not USE_SYNC_SEND else 'СИНХРОННО'})...")
                    try:
                        if USE_SYNC_SEND:
                            success = send_telegram_sync(updated_dict)
                        else:
                            # Используем новую функцию отправки с поддержкой локальных файлов
                            success = await send_telegram_message_async(updated_dict)
                            
                        if success:
                            logger.info(f"[{idx+1}] ✅ Объявление успешно отправлено в Telegram")
                            stats['telegram_success'] += 1
                        else:
                            logger.warning(f"[{idx+1}] ❌ Ошибка при отправке в Telegram")
                    except Exception as telegram_err:
                        logger.error(f"[{idx+1}] ❌ Ошибка Telegram: {telegram_err}", exc_info=True)
                
                stats['parsing_success'] += 1
                stats['total_success'] += 1
                logger.info(f"[{idx+1}] ✅ УСПЕХ | Парсинг: ✅ | Telegram: {'✅' if SEND_TO_TELEGRAM and stats['telegram_success'] > stats['telegram_success_prev'] else '❌'}")
                stats['telegram_success_prev'] = stats['telegram_success']  # Сохраняем текущее значение для следующего сравнения
                return updated_dict
            else:
                logger.error(f"[{idx+1}] ❌ Не удалось извлечь данные из {url}")
                stats['parsing_fail'] += 1
                return None
                
        except Exception as e:
            logger.error(f"[{idx+1}] ❌ Ошибка при обработке объявления {url}: {e}", exc_info=True)
            stats['parsing_fail'] += 1
            return None
        finally:
            # Закрытие ресурсов Playwright, если они еще открыты
            try:
                if parser and hasattr(parser, '_close_playwright'):
                    await parser._close_playwright()
                    logger.info(f"[{idx+1}] Ресурсы Playwright закрыты (finally).")
            except Exception as close_err:
                logger.warning(f"[{idx+1}] Ошибка при закрытии ресурсов Playwright: {close_err}")
    except Exception as e:
        logger.error(f"[{idx+1}] Критическая ошибка при обработке объявления: {e}", exc_info=True)
        stats['parsing_fail'] += 1
        return None

# --- Основная асинхронная функция --- 
async def test_multiple_listings():
    """Запускает тестирование на множественных объявлениях."""
    # Логирование запуска
    logger.info("Запуск тестирования множественных объявлений...")
    logger.info(f"=== ТЕСТИРОВАНИЕ {len(TEST_URLS)} ОБЪЯВЛЕНИЙ: ПАРСИНГ + TELEGRAM ===")
    logger.info(f"Отправка в Telegram: {'ВКЛЮЧЕНА' if SEND_TO_TELEGRAM else 'ОТКЛЮЧЕНА'}")
    logger.info(f"Метод отправки: {'АСИНХРОННЫЙ' if not USE_SYNC_SEND else 'СИНХРОННЫЙ'}")
    
    # Инициализация прокси
    smartproxy_config = {
        "server": "uy.smartproxy.com:15001",
        "user_pattern": "spgai22txz",
        "password": "jtx6i24Jpb~eweNw2eo"
    }
    logger.info(f"Конфигурация прокси: сервер={smartproxy_config['server']}, пользователь={smartproxy_config['user_pattern']}")
    
    # Результаты
    results = []
    
    # Статистика для тестов
    stats = {
        'total': len(TEST_URLS),
        'parsing_success': 0,
        'parsing_fail': 0,
        'telegram_success': 0,
        'telegram_success_prev': 0,
        'total_success': 0
    }
    
    # Обработка каждого URL
    for i, url in enumerate(TEST_URLS):
        # Обработка одного объявления
        result = await handle_single_listing(i, url, smartproxy_config, stats)
        results.append(result)
        
        # Пауза между отправками
        if SEND_TO_TELEGRAM and i < len(TEST_URLS) - 1:
            logger.info(f"Пауза {DELAY_BETWEEN_SENDS} секунд перед следующим объявлением...")
            await asyncio.sleep(DELAY_BETWEEN_SENDS)
    
    # Сводка результатов
    logger.info("=== ИТОГОВЫЕ РЕЗУЛЬТАТЫ ===")
    logger.info(f"Всего объявлений: {len(results)}")
    parse_success_count = sum(1 for r in results if r is not None)
    logger.info(f"Успешно спарсено: {parse_success_count}/{len(results)}")
    
    if SEND_TO_TELEGRAM:
        send_success_count = sum(1 for r in results if r is not None)
        logger.info(f"Успешно отправлено: {send_success_count}/{len(results)}")
    
    # Сохранение общего отчета
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": timestamp,
        "total": len(results),
        "parse_success": parse_success_count,
        "send_success": send_success_count if SEND_TO_TELEGRAM else None,
        "results": results
    }
    
    report_path = save_json_data(report, f"ml_multiple_test_{timestamp}.json")
    logger.info(f"Полный отчет сохранен: {report_path}")
    
    # Возвращаем True если все тесты успешны
    return all(r is not None for r in results)

# Вспомогательная функция для сохранения JSON
def save_json_data(data: Dict[str, Any], filename: str) -> str:
    """Сохраняет данные в JSON файл и возвращает путь."""
    report_dir = os.path.join(PROJECT_ROOT, "test_results")
    os.makedirs(report_dir, exist_ok=True)
    filepath = os.path.join(report_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Данные сохранены в файл: {filepath}")
    return filepath

# --- Точка входа ---
if __name__ == "__main__":
    logger.info("Запуск тестирования множественных объявлений...")
    success = asyncio.run(test_multiple_listings())
    sys.exit(0 if success else 1) 