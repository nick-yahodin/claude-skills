import logging
import asyncio
import argparse
from dotenv import load_dotenv
import os
import random
import sys
from typing import List
from pathlib import Path

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
env_path = URUGUAYLANDS_ROOT / 'config' / '.env' # <-- Путь относительно URUGUAYLANDS_ROOT
load_dotenv(dotenv_path=env_path)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestGallito")
logger.info(f"Загружены переменные из {env_path}")

# --- ИЗМЕНЕННЫЕ ИМПОРТЫ --- 
try:
    # Теперь импортируем относительно UruguayLands
    from config import settings
    from app.parsers.gallito import GallitoParser
    from app.models import Listing
except ImportError as e:
    logger.error(f"Не удалось импортировать компоненты: {e}")
    settings = None
    sys.exit(1)

# --- Остальной код без изменений --- 
async def main(num_listings_to_process: int):
    logger.info("--- Запуск теста парсинга Gallito (двухэтапный) ---")

    parser = GallitoParser()
    logger.info(f"--- Initialized parser: {parser.SOURCE_NAME} ---")

    all_listings_data: List[Listing] = []
    try:
        logger.info("Manually initializing browser with headless=False")
        # Используем метод инициализации/закрытия из базового парсера
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


        # --- Этап 1: Получение URL со страницы списка ---
        page_url = await parser._get_page_url(1)
        logger.info(f"Navigating to list page: {page_url}")
        # Используем корректный переход через page
        await parser.page.goto(page_url, wait_until='domcontentloaded', timeout=60000)
        
        logger.info("Extracting listing URLs from list page...")
        # Передаем page в метод
        listing_urls = await parser._extract_listings_from_page(parser.page) 
        logger.info(f"Found {len(listing_urls)} unique URLs on page 1.")

        # Ограничиваем количество URL для обработки
        urls_to_process = listing_urls[:num_listings_to_process]
        logger.info(f"Processing details for {len(urls_to_process)} URLs...")

        # --- Этап 2: Обработка каждой страницы деталей ---
        for i, detail_url in enumerate(urls_to_process):
            logger.info(f"--- Processing URL {i+1}/{len(urls_to_process)}: {detail_url} ---")
            try:
                # Переход на страницу деталей и извлечение данных одним методом
                listing_data_dict = await parser._extract_data_from_detail_page(parser.page, detail_url)
                
                if listing_data_dict:
                    try:
                        # Валидация и добавление в список
                        listing_obj = Listing(**listing_data_dict)
                        all_listings_data.append(listing_obj)
                        logger.info(f"Successfully parsed: {listing_obj.title} ({listing_obj.price})")
                    except Exception as pydantic_err:
                         logger.warning(f"Pydantic validation error for {detail_url}: {pydantic_err}")
                else:
                     logger.warning(f"Could not extract data from detail page: {detail_url}")

            except Exception as detail_err:
                logger.exception(f"Error processing detail page {detail_url}: {detail_err}")
            
            # Добавляем задержку между обработкой страниц деталей
            if i < len(urls_to_process) - 1:
                 await parser._delay()

        # --- Логирование результатов ---
        logger.info(f"Finished processing. Total listings parsed: {len(all_listings_data)}")
        if all_listings_data:
            logger.info("--- Parsed Listings Summary ---")
            for i, listing in enumerate(all_listings_data):
                 logger.info(f" Listing {i+1}:")
                 logger.info(f"  URL: {listing.url}")
                 logger.info(f"  Title: {listing.title}")
                 logger.info(f"  Price: {listing.price}")
                 logger.info(f"  Location: {listing.location}")
                 logger.info(f"  Area: {listing.area}")
                 logger.info(f"  Image: {listing.image_url}")
                 # Проверяем наличие описания перед срезом
                 desc_preview = listing.description[:100] + '...' if listing.description else "N/A"
                 logger.info(f"  Desc (first 100 chars): {desc_preview}")
                 logger.info(f"  Utils: {listing.utilities}")
        else:
            logger.warning("No listings were successfully parsed from detail pages.")

        logger.info("--- Тест парсинга Gallito (двухэтапный) завершен успешно ---")

    except Exception as e:
        logger.exception(f"Произошла ошибка во время теста: {e}")
    finally:
         # Используем метод базового класса для закрытия
         await parser._close_playwright()
         logger.info("Playwright resources closed.")


if __name__ == "__main__":
    parser_arg = argparse.ArgumentParser(description="Тест двухэтапного парсинга объявлений Gallito.")
    parser_arg.add_argument('num_listings', type=int, nargs='?', default=3,
                        help='Количество объявлений для обработки (по умолчанию: 3)')
    args = parser_arg.parse_args()
    logger.info(f"--- Запуск скрипта {__file__} с аргументом: {args.num_listings} ---")
    asyncio.run(main(args.num_listings)) 