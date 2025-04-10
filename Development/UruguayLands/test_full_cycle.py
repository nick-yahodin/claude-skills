#!/usr/bin/env python3
"""
Тестирование полного цикла парсинга MercadoLibre с обработкой Base64-изображений.
"""

import os
import sys
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any
from pathlib import Path

# Добавляем путь к корневой директории проекта
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('CycleTest')

# Импортируем компоненты приложения
from app.parsers.mercadolibre import MercadoLibreParser
from app.telegram_poster import post_to_telegram, send_telegram_message_async

# Ссылки для тестирования (с вероятным наличием Base64 изображений или других сложных случаев)
TEST_URLS = [
    "https://articulo.mercadolibre.com.uy/MLU-688357290-venta-terreno-punta-del-este-braglia-1691-_JM",
    "https://articulo.mercadolibre.com.uy/MLU-747239401-venta-terreno-100000-m2-excelente-para-inversion-_JM",
    "https://articulo.mercadolibre.com.uy/MLU-707739404-barrio-abierto-en-ruta-21-los-ceibos-_JM"
]

# Конфигурация прокси
SMARTPROXY_CONFIG = {
    "server": "http://gate.smartproxy.com:10005",
    "user_pattern": "spgai22txz",
    "password": "jtx6i24Jpb~ewWaFA9"
}

async def test_mercadolibre_parser():
    """Тестирует полный цикл парсинга MercadoLibre с обработкой деталей."""
    logger.info("Запуск теста полного цикла парсинга MercadoLibre")
    
    # Создаем папки для хранения результатов
    os.makedirs("test_results", exist_ok=True)
    os.makedirs("images", exist_ok=True)
    
    # Инициализируем парсер
    parser = MercadoLibreParser(
        smartproxy_config=SMARTPROXY_CONFIG,
        headless_mode=False  # False для отображения браузера
    )
    
    results = []
    
    try:
        # Инициализируем браузер
        logger.info("Инициализация браузера...")
        context = await parser._create_browser_context()
        if not context:
            raise Exception("Не удалось создать контекст браузера")
        
        for i, url in enumerate(TEST_URLS):
            logger.info(f"=== Тестирование URL {i+1}/{len(TEST_URLS)}: {url} ===")
            
            try:
                # Создаем страницу для каждого URL
                page = await context.new_page()
                
                # Переходим на страницу
                logger.info(f"Загрузка страницы: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Делаем скриншот для отладки
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = f"test_results/screenshot_{i+1}_{timestamp}.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"Скриншот сохранен: {screenshot_path}")
                
                # Базовая информация для объекта Listing
                from app.models import Listing
                listing = Listing(
                    url=url,
                    source="mercadolibre",
                    title="Test Listing",
                    area=None,
                    location=None,
                    price=None,
                    image_url=None
                )
                
                # Извлекаем данные со страницы
                logger.info("Извлечение данных...")
                updated_listing = await parser._extract_data_from_detail_page(page, listing)
                
                if updated_listing:
                    logger.info("Данные успешно извлечены:")
                    logger.info(f"- Заголовок: {updated_listing.title}")
                    logger.info(f"- Цена: {updated_listing.price}")
                    logger.info(f"- Локация: {updated_listing.location}")
                    logger.info(f"- Площадь: {updated_listing.area}")
                    logger.info(f"- Описание: {updated_listing.description[:100] if updated_listing.description else None}...")
                    # Преобразуем URL в строку для безопасного доступа к срезу
                    img_url_str = str(updated_listing.image_url) if updated_listing.image_url else None
                    logger.info(f"- Изображение: {img_url_str[:70] if img_url_str else None}...")
                    
                    # Сохраняем результаты в JSON
                    listing_data = updated_listing.model_dump()
                    
                    # Преобразуем URL-объекты в строки для JSON-сериализации
                    if 'url' in listing_data and not isinstance(listing_data['url'], str):
                        listing_data['url'] = str(listing_data['url'])
                    if 'image_url' in listing_data and not isinstance(listing_data['image_url'], str):
                        listing_data['image_url'] = str(listing_data['image_url'])
                    
                    # Преобразуем datetime в строки для JSON-сериализации
                    for field in ['date_scraped', 'date_published', 'date_added', 'date_updated', 'posted_date']:
                        if field in listing_data and listing_data[field] is not None:
                            if hasattr(listing_data[field], 'isoformat'):
                                listing_data[field] = listing_data[field].isoformat()
                    
                    # Пытаемся отправить в Telegram
                    logger.info("Отправка в Telegram...")
                    try:
                        # Добавляем хештеги для полноценной отправки
                        listing_data['hashtags'] = ["#TestCycle", "#Uruguay", "#MercadoLibre", "#Base64Test"]
                        
                        # Отправляем через новую функцию
                        success = await send_telegram_message_async(listing_data)
                        
                        if success:
                            logger.info("✅ Сообщение успешно отправлено в Telegram!")
                        else:
                            logger.error("❌ Ошибка при отправке в Telegram")
                    except Exception as telegram_err:
                        logger.error(f"❌ Исключение при отправке в Telegram: {telegram_err}", exc_info=True)
                    
                    # Сохраняем результаты
                    json_path = f"test_results/listing_{i+1}_{timestamp}.json"
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(listing_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"Данные сохранены в {json_path}")
                    
                    results.append({
                        "url": url,
                        "success": True,
                        "data": listing_data
                    })
                else:
                    logger.error(f"Не удалось извлечь данные для URL: {url}")
                    results.append({
                        "url": url,
                        "success": False,
                        "error": "Failed to extract data"
                    })
                
                # Закрываем страницу
                await page.close()
                
                # Пауза между запросами
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"Ошибка при обработке URL {url}: {e}", exc_info=True)
                results.append({
                    "url": url,
                    "success": False,
                    "error": str(e)
                })
                
                # В случае ошибки делаем скриншот, если страница все еще доступна
                try:
                    if 'page' in locals() and page and not page.is_closed():
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        error_screenshot = f"test_results/error_{i+1}_{timestamp}.png"
                        await page.screenshot(path=error_screenshot)
                        logger.info(f"Скриншот ошибки сохранен: {error_screenshot}")
                        await page.close()
                except Exception as ss_err:
                    logger.warning(f"Не удалось сохранить скриншот ошибки: {ss_err}")
        
        # Итоговые результаты
        logger.info("=== РЕЗУЛЬТАТЫ ТЕСТА ===")
        logger.info(f"Всего URL: {len(TEST_URLS)}")
        logger.info(f"Успешно обработано: {sum(1 for r in results if r['success'])}/{len(TEST_URLS)}")
        
        # Проверка наличия Base64-изображений
        base64_images = []
        for i, result in enumerate(results):
            if result['success'] and 'data' in result:
                image_url = result['data'].get('image_url', '')
                # Преобразуем в строку, если image_url не является строкой
                if image_url and not isinstance(image_url, str):
                    image_url = str(image_url)
                
                if image_url and os.path.isfile(image_url) and '/images/' in image_url:
                    base64_images.append(image_url)
        
        if base64_images:
            logger.info(f"Найдено Base64-изображений: {len(base64_images)}")
            for img in base64_images:
                logger.info(f"- {img} (размер: {os.path.getsize(img)} байт)")
        else:
            logger.info("Base64-изображений не найдено")
        
        # Сохраняем итоговый отчет
        report_path = f"test_results/full_cycle_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total_urls": len(TEST_URLS),
                "success_count": sum(1 for r in results if r['success']),
                "base64_images": base64_images,
                "results": results
            }, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Полный отчет сохранен: {report_path}")
    
    except Exception as e:
        logger.error(f"Критическая ошибка теста: {e}", exc_info=True)
    finally:
        # Закрываем браузер
        logger.info("Закрытие ресурсов Playwright...")
        await parser._close_playwright()
        logger.info("Ресурсы Playwright закрыты.")
    
    return results

if __name__ == "__main__":
    logger.info("Запуск теста полного цикла парсинга с поддержкой Base64")
    asyncio.run(test_mercadolibre_parser())
    logger.info("Тест завершен.") 