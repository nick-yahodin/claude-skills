#!/usr/bin/env python3
"""
Тестирование полного производственного цикла парсера MercadoLibre.
Включает:
1. Запуск парсера с настоящими параметрами
2. Обработку данных, включая Base64 изображения
3. Отправку сообщений в Telegram
"""

import os
import sys
import json
import logging
import asyncio
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import time

# Добавляем путь к корневой директории проекта
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"test_production_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)
logger = logging.getLogger('ProductionTest')

# Импортируем компоненты приложения
from app.parsers.mercadolibre import MercadoLibreParser
from app.telegram_poster import post_to_telegram, send_telegram_message_async, send_telegram_sync
from app.listing_manager import ListingManager
from app.models import Listing
try:
    from app.base64_handler import process_and_save_base64_image
    BASE64_MODULE_AVAILABLE = True
except ImportError:
    BASE64_MODULE_AVAILABLE = False

# Конфигурация прокси по умолчанию
DEFAULT_SMARTPROXY_CONFIG = {
    "server": "http://gate.smartproxy.com:10005",
    "user_pattern": "spgai22txz",
    "password": "jtx6i24Jpb~ewWaFA9"
}

# Тестовые URL для проверки деталей
TEST_URLS = [
    "https://articulo.mercadolibre.com.uy/MLU-688357290-venta-terreno-punta-del-este-braglia-1691-_JM",
    "https://articulo.mercadolibre.com.uy/MLU-707739404-barrio-abierto-en-ruta-21-los-ceibos-_JM"
]

class ProductionTestRunner:
    """Класс для тестирования производственного цикла."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "test_id": f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "config": config,
            "steps": [],
            "errors": [],
            "listings_found": 0,
            "listings_processed": 0,
            "images_found": 0,
            "base64_images": 0,
            "telegram_sent": 0
        }
        self.listing_manager = ListingManager(
            Path(self.config.get("state_file", "test_production_seen.json"))
        )
        
        # Создаем необходимые директории
        os.makedirs("images", exist_ok=True)
        os.makedirs("test_results", exist_ok=True)
        os.makedirs("errors", exist_ok=True)
    
    def log_step(self, step_name: str, result: str, details: Optional[Dict] = None):
        """Логирует шаг теста и добавляет его в отчет."""
        logger.info(f"STEP: {step_name} - {result}")
        
        step_data = {
            "name": step_name,
            "time": datetime.now().isoformat(),
            "result": result
        }
        
        if details:
            step_data["details"] = details
            
        self.results["steps"].append(step_data)
    
    def log_error(self, step_name: str, error_message: str, exception: Optional[Exception] = None):
        """Логирует ошибку и добавляет её в отчет."""
        logger.error(f"ERROR in {step_name}: {error_message}")
        
        error_data = {
            "step": step_name,
            "time": datetime.now().isoformat(),
            "message": error_message
        }
        
        if exception:
            error_data["exception"] = str(exception)
            error_data["exception_type"] = type(exception).__name__
            
        self.results["errors"].append(error_data)
    
    async def run_full_test(self):
        """Запускает полный тест производственного цикла."""
        try:
            # Шаг 1: Инициализация парсера
            self.log_step("init_parser", "Инициализация парсера MercadoLibre")
            
            parser = MercadoLibreParser(
                smartproxy_config=self.config.get("smartproxy", DEFAULT_SMARTPROXY_CONFIG),
                headless_mode=self.config.get("headless", True),
                max_retries=self.config.get("max_retries", 3)
            )
            
            # Шаг 2: Запуск парсера и сбор данных
            self.log_step("run_parser", "Запуск парсера и сбор данных с сайта")
            
            # Инициализируем Playwright с новым методом
            browser_init_success = await parser._init_playwright(headless=self.config.get("headless", True))
            if not browser_init_success:
                self.log_error("initialize_playwright", "Не удалось инициализировать Playwright", None)
                return False
                
            # Шаг 2.1: Запуск парсера и сбор данных
            self.log_step("run_parser", f"Запуск парсера с max_pages={self.config.get('max_pages', 1)}")
            
            try:
                # Запускаем парсер с обработкой деталей, если это указано в конфигурации
                process_details = self.config.get("process_details", False)
                listings = await parser.run(
                    max_pages=self.config.get("max_pages", 1),
                    detail_processing=process_details
                )
                
                if not listings:
                    self.log_error("run_parser", "Парсер не вернул объявлений")
                else:
                    self.results["listings_found"] = len(listings)
                    self.log_step("run_parser", f"Найдено {len(listings)} объявлений")
            except Exception as parser_error:
                self.log_error("run_parser", "Ошибка при запуске парсера", parser_error)
                return False
            
            # Шаг 3: Закрытие парсера перед обработкой результатов
            self.log_step("close_parser", "Закрытие ресурсов парсера")
            
            try:
                await parser._close_playwright()
                await asyncio.sleep(2)  # Пауза для освобождения ресурсов
            except Exception as close_error:
                self.log_error("close_parser", "Ошибка при закрытии парсера", close_error)
            
            # Шаг 4: Обработка найденных объявлений
            self.log_step("process_listings", f"Обработка {len(listings)} объявлений")
            
            # Коллекция для хранения данных для отправки в Telegram
            telegram_queue = []
            
            for i, listing in enumerate(listings):
                try:
                    # Проверяем, видели ли мы это объявление раньше
                    listing_id = listing.id or str(listing.url)
                    
                    if listing_id in self.listing_manager.seen_ids:
                        logger.debug(f"Пропуск уже виденного объявления: {listing_id}")
                        continue
                    
                    # Подготавливаем данные для Telegram
                    listing_dict = listing.model_dump()
                    
                    # Преобразуем URL-объекты в строки
                    if not isinstance(listing_dict.get('url'), str) and listing_dict.get('url') is not None:
                        listing_dict['url'] = str(listing_dict['url'])
                    if not isinstance(listing_dict.get('image_url'), str) and listing_dict.get('image_url') is not None:
                        listing_dict['image_url'] = str(listing_dict['image_url'])
                    
                    # Преобразуем datetime объекты в строки
                    for field in ['date_scraped', 'date_published', 'date_added', 'date_updated']:
                        if field in listing_dict and listing_dict[field] is not None:
                            if hasattr(listing_dict[field], 'isoformat'):
                                listing_dict[field] = listing_dict[field].isoformat()
                    
                    # Добавляем хэштеги (если доступно)
                    try:
                        from app.hashtag_generator import generate_hashtags
                        listing_dict['hashtags'] = generate_hashtags(listing_dict)
                    except ImportError:
                        # Если модуль недоступен, используем базовые хэштеги
                        listing_dict['hashtags'] = ["#Uruguay", "#RealEstate", "#Test"]
                    
                    # Проверяем наличие Base64-изображений
                    if listing_dict.get('image_url') and isinstance(listing_dict['image_url'], str):
                        if listing_dict['image_url'].startswith('data:image'):
                            if BASE64_MODULE_AVAILABLE:
                                # Обрабатываем Base64 через новый модуль
                                img_path = process_and_save_base64_image(
                                    listing_dict['image_url'],
                                    listing_dict['url'],
                                    f"test_{i+1}"
                                )
                                if img_path:
                                    listing_dict['image_url'] = img_path
                                    self.results["base64_images"] += 1
                        elif 'images/' in listing_dict['image_url']:
                            # Уже обработанное Base64-изображение
                            self.results["base64_images"] += 1
                        else:
                            # Обычное URL-изображение
                            self.results["images_found"] += 1
                    
                    # Добавляем в очередь на отправку в Telegram
                    telegram_queue.append(listing_dict)
                    self.results["listings_processed"] += 1
                    
                    # Добавляем в список виденных
                    self.listing_manager.add_seen(listing_id)
                    
                except Exception as process_error:
                    self.log_error("process_listings", f"Ошибка при обработке объявления {i+1}/{len(listings)}", process_error)
            
            # Шаг 5: Сохранение промежуточных результатов
            self.log_step("save_results", "Сохранение промежуточных результатов")
            
            # Сохраняем список виденных объявлений
            self.listing_manager._save_state()
            
            # Сохраняем данные для отправки в Telegram
            with open(f"test_results/telegram_queue_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", 'w', encoding='utf-8') as f:
                json.dump(telegram_queue, f, ensure_ascii=False, indent=2, default=str)
            
            # Шаг 6: Отправка в Telegram
            if self.config.get("send_to_telegram", False):
                self.log_step("send_telegram", f"Отправка {len(telegram_queue)} объявлений в Telegram")
                
                successful_count = 0
                total_count = len(telegram_queue)
                
                for idx, listing_dict in enumerate(telegram_queue):
                    try:
                        logger.info(f"Отправка в Telegram {idx+1}/{total_count}: {listing_dict.get('url')}")
                        
                        # Отправка стратегия 1: Асинхронная отправка через python-telegram-bot
                        logger.info("Стратегия 1: Асинхронная отправка через python-telegram-bot")
                        
                        try:
                            success_async = await post_to_telegram(listing_dict)
                            if success_async:
                                successful_count += 1
                                logger.info(f"STEP: telegram_strategy_1 - Успешно отправлено {successful_count}/{total_count}")
                                # Продолжаем цикл к следующему объявлению, не пытаясь использовать вторую стратегию
                                continue
                            # Если post_to_telegram вернул False, это означает, что отправка не удалась
                            else:
                                logger.warning(f"Асинхронная отправка через python-telegram-bot вернула False")
                        except Exception as e:
                            if "'_io.BytesIO' object has no attribute 'file'" in str(e) and "Объявление успешно отправлено" in str(e):
                                # Это известная ошибка, но отправка фактически произошла успешно
                                successful_count += 1
                                logger.info(f"STEP: telegram_strategy_1 - Успешно отправлено {successful_count}/{total_count} (с известной ошибкой)")
                                continue
                            else:
                                logger.error(f"ERROR in telegram_strategy_1: {str(e)}")
                            
                        # Выдерживаем паузу между стратегиями
                        time.sleep(2)

                        # Стратегия 2: Синхронная отправка через requests
                        try:
                            logger.info("Стратегия 2: Синхронная отправка через requests")
                            success = send_telegram_sync(listing_dict)
                            if success:
                                successful_count += 1
                                self.log_step("telegram_strategy_2", f"Успешно отправлено {idx+1}/{total_count}")
                            else:
                                self.log_error("telegram_strategy_2", "Неудачная отправка")
                        except Exception as tg_err_2:
                            self.log_error("telegram_strategy_2", "Ошибка при отправке", tg_err_2)
                            
                        # Пауза между отправками
                        if idx < total_count - 1:
                            delay = self.config.get("telegram_delay", 5)
                            logger.info(f"Пауза {delay} сек перед следующей отправкой...")
                            await asyncio.sleep(delay)
                        
                    except Exception as send_error:
                        self.log_error("send_telegram", f"Общая ошибка при отправке {idx+1}/{total_count}", send_error)
                
                self.results["telegram_sent"] = successful_count
                self.log_step("send_telegram", f"Всего успешно отправлено: {successful_count}/{total_count}")
            else:
                self.log_step("send_telegram", "Отправка в Telegram отключена в конфигурации")
            
            # Шаг 7: Формирование итогового отчета
            self.log_step("final_report", "Формирование итогового отчета")
            
            # Добавляем итоговую статистику
            self.results["success"] = len(self.results["errors"]) == 0
            self.results["end_time"] = datetime.now().isoformat()
            
            # Сохраняем отчет
            report_path = f"test_results/production_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(self.results, f, ensure_ascii=False, indent=2, default=str)
            
            logger.info(f"Итоговый отчет сохранен: {report_path}")
            
            # Вывод краткой сводки
            logger.info("=== СВОДКА ТЕСТИРОВАНИЯ ===")
            logger.info(f"Найдено объявлений: {self.results['listings_found']}")
            logger.info(f"Обработано объявлений: {self.results['listings_processed']}")
            logger.info(f"Обнаружено обычных изображений: {self.results['images_found']}")
            logger.info(f"Обнаружено Base64-изображений: {self.results['base64_images']}")
            logger.info(f"Отправлено в Telegram: {self.results['telegram_sent']}")
            logger.info(f"Ошибок: {len(self.results['errors'])}")
            logger.info(f"Статус: {'Успешно' if self.results['success'] else 'С ошибками'}")
            
        except Exception as test_error:
            self.log_error("run_full_test", "Критическая ошибка при выполнении теста", test_error)
            
            # Сохраняем отчет даже при критической ошибке
            self.results["success"] = False
            self.results["end_time"] = datetime.now().isoformat()
            self.results["critical_error"] = str(test_error)
            
            error_report_path = f"test_results/error_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(error_report_path, 'w', encoding='utf-8') as f:
                json.dump(self.results, f, ensure_ascii=False, indent=2, default=str)
            
            logger.error(f"Отчет об ошибке сохранен: {error_report_path}")

def parse_args():
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(description="Тестирование производственного цикла парсера MercadoLibre")
    parser.add_argument('--headless', action='store_true', help='Запускать браузер в режиме headless')
    parser.add_argument('--pages', type=int, default=1, help='Максимальное количество страниц для парсинга')
    parser.add_argument('--send', action='store_true', help='Отправлять сообщения в Telegram')
    parser.add_argument('--delay', type=int, default=1, help='Задержка между отправками в Telegram')
    parser.add_argument('--details', action='store_true', help='Включить обработку деталей объявлений')
    
    return parser.parse_args()

async def main():
    """Основная функция для запуска теста."""
    # Аргументы командной строки
    args = parse_args()
    
    # Конфигурация для теста
    config = {
        "smartproxy": DEFAULT_SMARTPROXY_CONFIG,
        "headless": args.headless,
        "max_pages": args.pages,
        "send_to_telegram": args.send,
        "telegram_delay": args.delay,
        "process_details": True,  # Всегда включаем обработку деталей для получения изображений
        "max_retries": 3,
        "delay_range": (2, 5),
        "state_file": "test_production_seen.json"
    }
    
    # Создаем и запускаем тест
    runner = ProductionTestRunner(config)
    await runner.run_full_test()

if __name__ == "__main__":
    logger.info("Запуск теста производственного цикла")
    asyncio.run(main())
    logger.info("Тест завершен") 