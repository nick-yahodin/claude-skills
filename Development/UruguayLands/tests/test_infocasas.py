import logging
import asyncio
import argparse
from dotenv import load_dotenv
import os
import random
import sys
from typing import List # Добавляем List
from pathlib import Path # Добавляем Path

# --- ИЗМЕНЕННЫЕ ПУТИ --- 
# Определяем корень проекта (папку, содержащую UruguayLands)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
# Определяем корень пакета UruguayLands
URUGUAYLANDS_ROOT = Path(__file__).parent.parent.resolve()

# Добавляем корень проекта и корень UruguayLands в sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(URUGUAYLANDS_ROOT) not in sys.path:
    sys.path.insert(1, str(URUGUAYLANDS_ROOT))

print("--- Current sys.path: ---")
print(sys.path)
print("-------------------------")

# Загрузка переменных окружения из UruguayLands/config/.env
env_path = URUGUAYLANDS_ROOT / 'config' / '.env'
load_dotenv(dotenv_path=env_path)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestInfoCasas")
logger.info(f"Загружены переменные из {env_path}")

# --- ИЗМЕНЕННЫЕ ИМПОРТЫ --- 
try:
    # Импортируем относительно UruguayLands
    from config import settings
    from app.parsers.infocasas import InfoCasasParser
    from app.models import Listing
except ImportError as e:
    logger.error(f"Не удалось импортировать компоненты: {e}")
    settings = None
    sys.exit(1)

# --- Остальной код почти без изменений --- 
async def main(num_listings_to_parse: int):
    logger.info("--- Запуск теста парсинга InfoCasas (без отправки) ---")

    parser = InfoCasasParser()
    logger.info(f"--- Initialized parser: {parser.SOURCE_NAME} ---")
    logger.info("Starting parsing...")

    listings: List[Listing] = []
    try:
        logger.info("Manually initializing browser with headless=False")
        # Используем методы базового класса для управления браузером
        await parser._init_playwright(headless=False)
        if not parser.browser:
             raise Exception("Browser failed to initialize")
        parser.context = await parser._create_context()
        if not parser.context:
             raise Exception("Browser context failed to initialize")
        parser.page = await parser.context.new_page()
        if not parser.page:
             raise Exception("Browser page failed to initialize")
        logger.info("Browser and page initialized successfully.")

        page_url = await parser._get_page_url(1)
        logger.info(f"Manually navigating to page: {page_url}")
        # Используем page из парсера
        await parser.page.goto(page_url, wait_until='domcontentloaded', timeout=60000)

        logger.info("Manually extracting listings from page...")
        # Передаем page из парсера
        listings = await parser._extract_listings_from_page(parser.page)
        logger.info(f"Extracted {len(listings)} listings from page 1.")

        listings_to_log = listings[:num_listings_to_parse]
        logger.info(f"Logging details for {len(listings_to_log)} listings:")
        for i, listing in enumerate(listings_to_log):
            logger.info(f"--- Listing {i+1} ---")
            logger.info(f"  URL: {listing.url}")
            logger.info(f"  Title: {listing.title}")
            logger.info(f"  Price: {listing.price}")
            logger.info(f"  Location: {listing.location}")
            logger.info(f"  Area: {listing.area}")
            logger.info(f"  Image: {listing.image_url}")
            # Добавим вывод описания и утилит, если они есть
            desc_preview = listing.description[:100] + '...' if listing.description else "N/A"
            logger.info(f"  Desc (first 100 chars): {desc_preview}")
            logger.info(f"  Utils: {listing.utilities}")


        if not listings:
            logger.warning("Парсер не вернул объявлений.")

        logger.info("--- Тест парсинга InfoCasas завершен успешно ---")

    except Exception as e:
        logger.exception(f"Произошла ошибка во время теста: {e}")
    finally:
        # Используем метод базового класса для закрытия
        await parser._close_playwright()
        logger.info("Playwright resources closed.")


if __name__ == "__main__":
    parser_arg = argparse.ArgumentParser(description="Тест парсинга объявлений InfoCasas.")
    parser_arg.add_argument('num_listings', type=int, nargs='?', default=5,
                        help='Количество объявлений для парсинга и вывода в лог (по умолчанию: 5)')
    args = parser_arg.parse_args()

    logger.info(f"--- Запуск скрипта {__file__} с аргументом: {args.num_listings} ---")
    asyncio.run(main(args.num_listings)) 