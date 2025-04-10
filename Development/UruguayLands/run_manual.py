#!/usr/bin/env python3
"""
Скрипт для ручного запуска парсеров UruguayLands.
Позволяет запустить один или все парсеры с заданными параметрами.
"""

import asyncio
import argparse
import logging
import json
import os
from pathlib import Path

# Загрузка переменных окружения (если есть)
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / "config" / ".env")

from app.parsers import AVAILABLE_PARSERS, get_parser

# Настройка логирования
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
log_file_path = LOGS_DIR / "manual_run.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] - %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ManualRun")

async def run_manual(parser_names: list[str], max_pages: int, headless: bool, proxy_file: Optional[str]):
    """Запускает парсеры вручную."""
    
    proxy_list = None
    if proxy_file:
        proxy_path = Path(proxy_file)
        if proxy_path.exists():
            try:
                with open(proxy_path, 'r') as f:
                    proxy_list = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                if proxy_list:
                     logger.info(f"Загружено {len(proxy_list)} прокси из файла {proxy_file}")
                else:
                     logger.warning(f"Файл прокси {proxy_file} пуст.")
            except Exception as e:
                 logger.error(f"Ошибка загрузки файла прокси {proxy_file}: {e}")
        else:
            logger.warning(f"Файл прокси не найден: {proxy_file}")

    if "all" in parser_names:
        parsers_to_run = list(AVAILABLE_PARSERS.keys())
    else:
        parsers_to_run = [name for name in parser_names if name in AVAILABLE_PARSERS]
        if len(parsers_to_run) != len(parser_names):
             logger.warning("Некоторые указанные парсеры не найдены.")
             
    if not parsers_to_run:
        logger.error("Не выбрано ни одного корректного парсера для запуска.")
        return
        
    logger.info(f"Запускаемые парсеры: {parsers_to_run}")
    logger.info(f"Макс. страниц: {max_pages}")
    logger.info(f"Headless режим: {headless}")
    logger.info(f"Прокси используются: {'Да' if proxy_list else 'Нет'}")

    all_results = []
    for parser_name in parsers_to_run:
        logger.info(f"--- Запуск парсера: {parser_name} ---")
        parser = get_parser(parser_name)
        if parser:
            parser.proxy_list = proxy_list # Передаем прокси
            try:
                results = await parser.parse(headless=headless, max_pages=max_pages)
                all_results.extend(results)
                logger.info(f"Парсер {parser_name} завершен. Найдено объявлений: {len(results)}")
            except Exception as e:
                logger.exception(f"Ошибка при выполнении парсера {parser_name}: {e}")
        else:
             logger.error(f"Парсер {parser_name} не найден.")
             
        # Небольшая пауза между парсерами
        if len(parsers_to_run) > 1:
            await asyncio.sleep(5)
            
    logger.info(f"--- Ручной запуск завершен. Всего найдено объявлений: {len(all_results)} ---")
    # Опционально: Сохранить все результаты в один файл?
    # save_all_manual_results(all_results)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ручной запуск парсеров UruguayLands.")
    parser.add_argument(
        "parser", 
        nargs='+', 
        help=f"Имя парсера для запуска ({', '.join(AVAILABLE_PARSERS.keys())}) или 'all' для запуска всех."
    )
    parser.add_argument(
        "--pages", '-p', 
        type=int, 
        default=1, 
        help="Максимальное количество страниц для парсинга (по умолчанию: 1)."
    )
    parser.add_argument(
        "--visible", '-v', 
        action='store_false', 
        dest='headless', 
        help="Показывать окно браузера при парсинге (по умолчанию: скрыт)."
    )
    parser.add_argument(
        "--proxy", 
        type=str, 
        default=None,
        help="Путь к файлу со списком прокси (каждый прокси на новой строке)."
    )
    parser.set_defaults(headless=True)
    
    args = parser.parse_args()
    
    asyncio.run(run_manual(args.parser, args.pages, args.headless, args.proxy)) 