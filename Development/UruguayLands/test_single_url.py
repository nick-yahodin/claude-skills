#!/usr/bin/env python3
"""
Скрипт для тестирования парсинга конкретных URL с MercadoLibre.
Позволяет проверить извлечение данных из указанных URL.
"""

import asyncio
import argparse
import logging
from datetime import datetime
import os
import sys
import json
from typing import List, Dict, Any, Optional

# Настройка путей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Импорт компонентов
from app.parsers.mercadolibre import MercadoLibreParser
from app.telegram_poster import post_to_telegram
from app.models import Listing

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("SingleURLTest")

async def test_single_url(url: str, headless: bool = False, send_to_telegram: bool = False) -> Optional[Dict[str, Any]]:
    """
    Тестирует парсинг конкретного URL с MercadoLibre.
    
    Args:
        url: URL для тестирования
        headless: Запускать браузер в режиме headless
        send_to_telegram: Отправлять результаты в Telegram
        
    Returns:
        Словарь с данными о листинге или None в случае ошибки
    """
    logger.info(f"Тестирование URL: {url}")
    
    # Инициализация парсера
    parser = MercadoLibreParser(headless_mode=headless)
    
    try:
        # Запускаем браузер используя публичный метод parse
        # Это запустит браузер и вернет пустой список результатов,
        # но установит все необходимые атрибуты в объекте парсера
        await parser.parse(max_pages=0)
        
        # Создаем пустой объект листинга с URL
        listing = Listing(
            url=url,
            title="Временный заголовок",
            source="mercadolibre",
            price="US$ 0",
            location="Uruguay",
            deal_type="Venta"
        )
        
        # Создаем страницу для работы
        page = await parser._browser_context.new_page()
        
        try:
            # Переходим на URL
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            # Небольшая пауза для загрузки контента
            await page.wait_for_timeout(2000)
            
            # Обработка деталей на странице
            updated_listing = await parser._extract_data_from_detail_page(page, listing)
            
            if updated_listing:
                logger.info("----- Результаты парсинга -----")
                logger.info(f"Заголовок: {updated_listing.title}")
                logger.info(f"Цена: {updated_listing.price}")
                logger.info(f"Локация: {updated_listing.location}")
                logger.info(f"Площадь: {updated_listing.area}")
                logger.info(f"Изображение: {updated_listing.image_url}")
                logger.info(f"Описание: {updated_listing.description and updated_listing.description[:100]}...")
                
                # Сохраняем результаты в JSON
                result_dir = "test_results"
                os.makedirs(result_dir, exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                result_file = f"{result_dir}/single_url_test_{timestamp}.json"
                
                with open(result_file, "w", encoding="utf-8") as f:
                    # Преобразуем объект pydantic в словарь
                    listing_dict = updated_listing.dict()
                    # Преобразуем URL к строке для сериализации
                    listing_dict["url"] = str(listing_dict["url"])
                    if listing_dict.get("image_url"):
                        listing_dict["image_url"] = str(listing_dict["image_url"])
                    
                    json.dump(listing_dict, f, ensure_ascii=False, indent=2)
                
                logger.info(f"Результаты сохранены в {result_file}")
                
                # Отправка в Telegram, если запрошено
                if send_to_telegram:
                    logger.info("Отправка результатов в Telegram...")
                    success = await post_to_telegram(updated_listing.dict())
                    if success:
                        logger.info("Сообщение успешно отправлено в Telegram")
                    else:
                        logger.error("Ошибка при отправке в Telegram")
                
                return updated_listing.dict()
            else:
                logger.error(f"Не удалось обработать URL: {url}")
                return None
                
        finally:
            # Закрываем страницу
            await page.close()
    
    except Exception as e:
        logger.error(f"Ошибка при тестировании URL: {e}", exc_info=True)
        return None
    
    finally:
        # Закрываем ресурсы
        await parser._clean_up()
        logger.info("Ресурсы парсера освобождены")

async def process_listing_details(parser: MercadoLibreParser, url: str) -> Optional[Listing]:
    """
    Вспомогательная функция для обработки деталей листинга.
    
    Args:
        parser: Инициализированный парсер
        url: URL для обработки
        
    Returns:
        Optional[Listing]: Обновленный объект листинга или None
    """
    try:
        # Создаем новый объект листинга
        listing = Listing(
            url=url,
            title="Временный заголовок",
            source="mercadolibre",
            price="US$ 0",
            location="Uruguay",
            deal_type="Venta"
        )
        
        # Создаем новую страницу
        page = await parser._browser_context.new_page()
        
        try:
            # Извлекаем данные
            return await parser._extract_data_from_detail_page(page, listing)
        finally:
            # Закрываем страницу
            await page.close()
    except Exception as e:
        logger.error(f"Ошибка при обработке деталей листинга: {e}")
        return None

async def test_multiple_urls(urls: List[str], headless: bool = False, send_to_telegram: bool = False) -> Dict[str, Any]:
    """
    Тестирует парсинг нескольких URL с MercadoLibre.
    
    Args:
        urls: Список URL для тестирования
        headless: Запускать браузер в режиме headless
        send_to_telegram: Отправлять результаты в Telegram
        
    Returns:
        Словарь с результатами парсинга
    """
    results = {
        "total": len(urls),
        "success": 0,
        "failed": 0,
        "listings": []
    }
    
    for i, url in enumerate(urls):
        logger.info(f"Обработка URL {i+1}/{len(urls)}: {url}")
        result = await test_single_url(url, headless, send_to_telegram)
        
        if result:
            results["success"] += 1
            results["listings"].append(result)
        else:
            results["failed"] += 1
    
    # Сохраняем сводные результаты в JSON
    result_dir = "test_results"
    os.makedirs(result_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = f"{result_dir}/multiple_urls_test_{timestamp}.json"
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Сводные результаты сохранены в {result_file}")
    logger.info(f"Всего URL: {results['total']}, Успешно: {results['success']}, Ошибок: {results['failed']}")
    
    return results

def parse_args():
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(description="Тестирование парсинга конкретных URL с MercadoLibre")
    parser.add_argument("--urls", nargs="+", help="Список URL для тестирования")
    parser.add_argument("--url-file", help="Файл со списком URL (по одному на строку)")
    parser.add_argument("--headless", action="store_true", help="Запускать браузер в режиме headless")
    parser.add_argument("--send", action="store_true", help="Отправлять результаты в Telegram")
    
    return parser.parse_args()

async def main():
    """Основная функция для запуска тестирования."""
    args = parse_args()
    
    urls = []
    
    # Получаем список URL из аргументов или файла
    if args.urls:
        urls = args.urls
    elif args.url_file:
        try:
            with open(args.url_file, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Ошибка при чтении файла URL: {e}")
            return
    else:
        # Предопределенные URL для тестирования
        urls = [
            "https://terreno.mercadolibre.com.uy/MLU-712986794-venta-terreno-loteo-barrio-privado-la-arbolada-fraccionamiento-costa-de-oro-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-704632172-lotes-entre-el-campo-y-el-bosque-a-un-minuto-del-mar-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-706539090-barrio-semi-privado-colonia-del-sacramento-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-639860029-terreno-en-barrio-privado-verde-mora-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-711738830-se-vende-terreno-220m2-con-casa-construida-y-espacio-para-auto-en-piedra-blancas-_JM"
        ]
    
    if not urls:
        logger.error("Не указаны URL для тестирования")
        return
    
    # Если указан только один URL, тестируем его отдельно
    if len(urls) == 1:
        await test_single_url(urls[0], args.headless, args.send)
    else:
        # Тестируем несколько URL
        await test_multiple_urls(urls, args.headless, args.send)

if __name__ == "__main__":
    asyncio.run(main()) 