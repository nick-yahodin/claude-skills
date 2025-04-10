#!/usr/bin/env python3
"""
Основной модуль приложения UruguayLands.
Запускает парсеры, обрабатывает объявления и отправляет их в Telegram.
"""

import asyncio
import importlib
import logging
import logging.config
import os
import sys
import time
import traceback
from pathlib import Path
from typing import List, Dict, Type, Optional, Any

from dotenv import load_dotenv
from playwright_stealth import stealth_async

# Добавляем корневую директорию проекта в sys.path, чтобы можно было импортировать модули парсеров
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Добавляем корневую папку в sys.path для импорта модулей приложения
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# Настройка логгирования до основных импортов, чтобы оно работало сразу
logger = None
def setup_logging(log_level_str: str):
    global logger
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    LOGGING_CONFIG['handlers']['console']['level'] = log_level
    # LOGGING_CONFIG['handlers']['file']['level'] = log_level # Если используете файл
    LOGGING_CONFIG['loggers']['']['level'] = log_level
    LOGGING_CONFIG['loggers']['app']['level'] = log_level
    LOGGING_CONFIG['loggers']['parsers']['level'] = log_level
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger('app.main') # Получаем логгер после конфигурации
    logger.info(f"Логгирование настроено на уровень: {log_level_str}")

# --- Конфигурация логгирования ---
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO', # Уровень по умолчанию, будет переопределен из .env
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
        # Можно добавить FileHandler для записи логов в файл
        # 'file': {
        #     'level': 'INFO',
        #     'class': 'logging.FileHandler',
        #     'filename': 'logs/app.log', # Убедитесь, что директория logs существует
        #     'formatter': 'standard',
        # },
    },
    'loggers': {
        '': { # Корневой логгер
            'handlers': ['console'], # Добавьте 'file' при необходимости
            'level': 'INFO',
            'propagate': True,
        },
        'app': { # Логгер для модулей приложения
             'handlers': ['console'],
             'level': 'INFO',
             'propagate': False, # Не передавать сообщения корневому логгеру
        },
        'parsers': { # Логгер для парсеров
             'handlers': ['console'],
             'level': 'INFO',
             'propagate': False,
        },
        # Уменьшаем уровень логгирования для httpx и playwright, чтобы не засорять вывод
        'httpx': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'playwright': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
         'asyncio': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        }
    }
}

# --- Загрузка конфигурации ---
def load_config() -> Dict[str, Any]:
    """Загружает конфигурацию из .env файла."""
    config = {
        "check_interval_minutes": int(os.getenv("CHECK_INTERVAL_MINUTES", 60)),
        "parsers_to_run": os.getenv("PARSERS_TO_RUN", "all").lower().split(','),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "telegram_delay_seconds": int(os.getenv("TELEGRAM_DELAY_SECONDS", 2)), # Задержка между постами
        "max_pages_per_run": int(os.getenv("MAX_PAGES_PER_RUN", "2")),
        "proxy_file_path": os.getenv("PROXY_FILE_PATH", None), # Добавляем чтение пути к файлу прокси
        "headless_mode": os.getenv("HEADLESS_MODE", "true").lower() == "true", # Добавляем чтение режима headless
        "smartproxy_server": os.getenv("SMARTPROXY_SERVER"),
        "smartproxy_user_pattern": os.getenv("SMARTPROXY_USER_PATTERN"),
        "smartproxy_password": os.getenv("SMARTPROXY_PASSWORD"),
    }
    # Обработка 'all'
    if "all" in config["parsers_to_run"]:
         config["parsers_to_run"] = ["all"] # Используем специальное значение 'all' внутри

    # Проверка наличия токена и ID чата (критично для работы)
    if not os.getenv("BOT_TOKEN") or not os.getenv("CHAT_ID"):
        print("Ошибка: Переменные окружения BOT_TOKEN и CHAT_ID должны быть установлены в config/.env")
        sys.exit(1)

    return config

# --- Загрузка .env и Настройка логгирования --- 
dotenv_path = PROJECT_ROOT / 'config' / '.env'
# Загружаем .env сначала
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)

# Загружаем конфиг, чтобы получить LOG_LEVEL
temp_config_for_log = load_config() 
# Настраиваем логгер
setup_logging(temp_config_for_log.get('log_level', 'INFO'))

# Теперь логгер доступен
if dotenv_path.exists():
    logger.info(f"Загрузка переменных окружения из {dotenv_path}")
else:
    logger.warning(f"Файл .env не найден по пути {dotenv_path}. Используются значения по умолчанию или переменные среды.")

# --- Модули приложения (после load_dotenv) ---
from app.listing_manager import ListingManager
from app.telegram_poster import post_to_telegram, format_telegram_message, send_telegram_direct, send_telegram_sync
# Закомментируем импорт хештегов, так как пока не используем
# from app.hashtag_generator import generate_hashtags 
from app.parsers.base import BaseParser
# <<< 1. Правильный импорт Listing >>>
from app.models import Listing

# --- Динамическая загрузка парсеров ---
def load_parsers(parsers_dir: Path = PROJECT_ROOT / 'app' / 'parsers') -> Dict[str, Type[BaseParser]]:
    """
    Динамически загружает классы парсеров из указанной директории.
    Ищет классы, унаследованные от BaseParser.
    """
    parsers_dict: Dict[str, Type[BaseParser]] = {}
    logger.info(f"Загрузка парсеров из директории: {parsers_dir}")
    # Добавим проверку существования директории
    if not parsers_dir.is_dir():
        logger.error(f"Директория парсеров не найдена: {parsers_dir}")
        return parsers_dict
        
    for filepath in parsers_dir.glob("*.py"):
        # Обновляем условие пропуска, base_parser.py и models.py теперь тоже в app/parsers
        if filepath.name == "__init__.py" or filepath.name == "base.py" or filepath.name == "models.py": 
            continue

        # Путь к модулю теперь относительно app
        module_name = f"app.parsers.{filepath.stem}" 
        try:
            module = importlib.import_module(module_name)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseParser) and attr is not BaseParser:
                    parser_name = attr.SOURCE_NAME.lower() # Используем имя источника как ключ
                    if parser_name in parsers_dict:
                         logger.warning(f"Обнаружен дубликат парсера для источника '{parser_name}' в модуле {module_name}. Используется первый найденный.")
                         continue
                    parsers_dict[parser_name] = attr
                    logger.info(f"Найден и загружен парсер: {attr.__name__} для источника '{parser_name}'")
        except ImportError as e:
            logger.error(f"Не удалось импортировать модуль {module_name}: {e}")
        except AttributeError as e:
            logger.error(f"Ошибка при загрузке парсера из модуля {module_name}: {e}. Убедитесь, что класс парсера определен и унаследован от BaseParser.")
        except Exception as e:
             logger.error(f"Непредвиденная ошибка при загрузке парсера из {module_name}: {e}", exc_info=True) # Добавлено exc_info

    if not parsers_dict:
        logger.warning("Не найдено ни одного парсера в директории parsers/. Проверьте наличие файлов парсеров.")

    return parsers_dict

# --- Загрузка списка прокси ---
def load_proxies(proxy_file_path: Optional[str]) -> Optional[List[str]]:
    """Загружает список прокси из файла."""
    if not proxy_file_path:
        logger.info("Файл прокси не указан (PROXY_FILE_PATH). Прокси не используются.")
        return None
    
    full_proxy_path = PROJECT_ROOT / proxy_file_path
    if not full_proxy_path.exists():
        logger.warning(f"Файл прокси не найден по указанному пути: {full_proxy_path}")
        return None
        
    try:
        with open(full_proxy_path, 'r') as f:
            proxies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        if proxies:
            logger.info(f"Загружено {len(proxies)} прокси из файла {full_proxy_path}")
            return proxies
        else:
            logger.warning(f"Файл прокси {full_proxy_path} пуст.")
            return None
    except Exception as e:
        logger.error(f"Ошибка при чтении файла прокси {full_proxy_path}: {e}")
        return None

# --- Обработка одного парсера --- (ВОССТАНОВЛЕННАЯ ФУНКЦИЯ)
async def process_parser(parser_name: str, listing_manager: ListingManager) -> int:
    """Запускает парсер по имени, обрабатывает результаты и отправляет в Телеграм."""
    parser_class = parsers_dict.get(parser_name)
    if not parser_class:
        logger.error(f"Парсер '{parser_name}' не найден. Доступные парсеры: {', '.join(parsers_dict.keys())}")
        return 0
    
    logger.info(f"--- Запуск парсера: {parser_name} ---")
    
    # Создаем конфигурацию прокси, если файл указан
    smartproxy_config = None
    if PROXY_FILE_PATH:
        smartproxy_config = load_smartproxy_config(PROXY_FILE_PATH)
        logger.debug(f"Checking Smartproxy config: server='{smartproxy_config.get('server')}', pattern='{smartproxy_config.get('user_pattern')}', password_present={bool(smartproxy_config.get('password'))}")
    
    # Создаем экземпляр парсера
    parser_instance = parser_class(
        smartproxy_config=smartproxy_config,
        headless_mode=HEADLESS_MODE,
        max_retries=MAX_RETRIES,
        request_delay_range=DELAY_RANGE
    )
    
    new_listings_count = 0
    all_processed_urls = []  # Для отслеживания всех URL с этого запуска
    
    try:
        # Запускаем парсер
        listings = await parser_instance.run(max_pages=MAX_PAGES)
        
        # Проверяем, есть ли результаты
        if not listings:
            logger.info(f"Парсер {parser_name} не нашел объявлений.")
            return 0
        
        logger.info(f"Парсер {parser_name} завершен. Найдено объявлений: {len(listings)}")
        
        # Сначала закрываем все ресурсы Playwright
        logger.info("Закрытие ресурсов Playwright перед отправкой в Telegram...")
        await parser_instance.close()
        
        # Добавляем небольшую паузу для полного освобождения ресурсов
        await asyncio.sleep(2)
        
        # Подготавливаем данные для отправки
        telegram_queue = []
        
        # Обрабатываем каждое объявление и формируем данные для Telegram
        for listing in listings:
            # Проверяем, видели ли мы это объявление раньше
            listing_id = listing.id or str(listing.url)
            url = str(listing.url)
            
            if listing_id in listing_manager.seen_listings:
                # Если URL уже был обработан ранее (из seen_listings)
                logger.debug(f"Пропуск уже виденного объявления: {listing_id}")
                continue
                
            if url in all_processed_urls:
                # Если URL уже был обработан в текущем запуске
                logger.debug(f"Пропуск дубликата URL с текущего запуска: {url}")
                continue
                
            all_processed_urls.append(url)
            
            # Оповещаем о новом объявлении
            logger.info(f"[НОВОЕ][{parser_name}] Найдено: {url}")
            
            # Конвертируем объект Listing в словарь и добавляем хэштеги
            try:
                listing_dict = listing.model_dump()
                
                # Преобразуем URL-объекты в строки (из Pydantic HttpUrl)
                if isinstance(listing_dict.get('url'), str) == False and listing_dict.get('url') is not None:
                    listing_dict['url'] = str(listing_dict['url'])
                if isinstance(listing_dict.get('image_url'), str) == False and listing_dict.get('image_url') is not None:
                    listing_dict['image_url'] = str(listing_dict['image_url'])
                
                # Преобразуем datetime объекты в строки
                for field in ['date_scraped', 'date_published', 'date_added', 'date_updated', 'posted_date']:
                    if field in listing_dict and listing_dict[field] is not None:
                        if hasattr(listing_dict[field], 'isoformat'):
                            listing_dict[field] = listing_dict[field].isoformat()
                
                # Генерируем хэштеги
                hashtags = hashtag_generator.generate_hashtags(listing_dict)
                listing_dict['hashtags'] = hashtags
                logger.debug(f"Сгенерированные хэштеги для ID {listing_id}: {hashtags}")
                
                # Добавляем в очередь на отправку
                telegram_queue.append(listing_dict)
                new_listings_count += 1
                
                # Добавляем в список виденных
                listing_manager.add_listing(listing_id)
            except Exception as e:
                logger.error(f"Ошибка при подготовке объявления {url}: {e}", exc_info=True)
        
        # Отправляем сообщения в Telegram с задержкой
        success_count = 0
        for idx, listing_dict in enumerate(telegram_queue):
            try:
                logger.info(f"Отправляем объявление: {listing_dict}")
                
                # Запускаем отправку в Telegram
                retry_success = False
                max_telegram_retries = 3
                
                for telegram_retry in range(max_telegram_retries):
                    try:
                        # Сначала пробуем через основную асинхронную функцию
                        if telegram_retry == 0:
                            success = await post_to_telegram(listing_dict)
                        else:
                            # При повторных попытках используем синхронную отправку
                            loop = asyncio.get_event_loop()
                            success = await loop.run_in_executor(
                                None, 
                                lambda: send_telegram_sync(listing_dict)
                            )
                        
                        if success:
                            retry_success = True
                            success_count += 1
                            break
                        else:
                            logger.warning(f"Неудачная отправка в Telegram (попытка {telegram_retry+1}/{max_telegram_retries})")
                            await asyncio.sleep(2 * (telegram_retry + 1))  # Увеличиваем задержку при повторных попытках
                    except Exception as telegram_err:
                        logger.error(f"Ошибка при отправке в Telegram (попытка {telegram_retry+1}/{max_telegram_retries}): {telegram_err}")
                        if telegram_retry < max_telegram_retries - 1:
                            await asyncio.sleep(2 * (telegram_retry + 1))
                
                if not retry_success:
                    logger.error(f"Не удалось отправить в Telegram после {max_telegram_retries} попыток: {listing_dict['url']}")
                
                # Делаем задержку между отправками в Telegram
                if idx < len(telegram_queue) - 1:  # Если не последнее сообщение
                    delay_seconds = random.uniform(TELEGRAM_DELAY_SECONDS * 0.8, TELEGRAM_DELAY_SECONDS * 1.2)
                    logger.debug(f"Задержка {delay_seconds:.2f} секунд перед отправкой следующего сообщения...")
                    await asyncio.sleep(delay_seconds)
            except Exception as e:
                logger.error(f"[ОШИБКА ОБРАБОТКИ][{parser_name}] Объявление {listing_dict.get('url')}: {e}", exc_info=True)
                continue
        
        logger.info(f"[{parser_name}] Отправлено новых объявлений в Telegram: {success_count}")
    except Exception as e:
        logger.error(f"Ошибка при запуске парсера {parser_name}: {e}", exc_info=True)
    finally:
        # Убедимся, что ресурсы парсера закрыты
        try:
            if hasattr(parser_instance, 'close') and callable(parser_instance.close):
                await parser_instance.close()
        except Exception as close_err:
            logger.warning(f"Ошибка при закрытии парсера {parser_name}: {close_err}")
    
    logger.info(f"--- Парсер {parser_name} завершил работу ---")
    return new_listings_count

# --- Основной цикл --- (ВОССТАНОВЛЕННАЯ ФУНКЦИЯ с последовательным вызовом)
async def run_main_cycle(config: Dict[str, Any], available_parsers: Dict[str, Type[BaseParser]], manager: ListingManager, proxy_list: Optional[List[str]]):
    """Выполняет один цикл проверки объявлений, запуская парсеры последовательно."""
    logger.info("--- Начало нового цикла проверки ---")

    parsers_to_run_config = config['parsers_to_run']
    actual_parsers_to_run_names: List[str] = []

    # Определяем, какие парсеры запускать
    if "all" in parsers_to_run_config:
        actual_parsers_to_run_names = list(available_parsers.keys())
        logger.info(f"Запуск ВСЕХ доступных парсеров последовательно.")
    else:
        for name in parsers_to_run_config:
            clean_name = name.strip().lower()
            if clean_name in available_parsers:
                actual_parsers_to_run_names.append(clean_name)
            else:
                logger.warning(f"Парсер с именем '{clean_name}', указанный в PARSERS_TO_RUN, не найден. Пропускается.")
        
        if not actual_parsers_to_run_names:
             logger.error("Нет доступных парсеров для запуска. Цикл пропускается.")
             logger.info("--- Цикл проверки завершен (нет активных парсеров) ---")
             return
        logger.info(f"Запуск парсеров последовательно: {', '.join(actual_parsers_to_run_names)}")

    # Запуск парсеров последовательно
    for name in actual_parsers_to_run_names: 
        ParserClass = available_parsers[name]
        try:
            # <<< Исправляем вызов: убираем proxy_list >>>
            await process_parser(name, manager)
        except Exception as e:
             logger.error(f"Неперехваченная ошибка при вызове process_parser для {name}: {e}", exc_info=True)
    
    # Сохраняем состояние после обработки всех парсеров в цикле
    manager._save_state()
    logger.info("Состояние менеджера объявлений сохранено.")

    logger.info("--- Цикл проверки завершен ---")


# --- Главная функция --- (ВОССТАНОВЛЕННАЯ)
async def main():
    """Главная асинхронная функция приложения."""
    config = load_config()
    setup_logging(config['log_level'])
    if logger is None: # Проверка логгера
        print("Критическая ошибка: Логгер не инициализирован.")
        sys.exit(1)

    logger.info("Запуск приложения UruguayLands")

    # Загрузка прокси
    proxy_list = load_proxies(config['proxy_file_path'])

    # Загрузка парсеров
    available_parsers = load_parsers()
    if not available_parsers:
        logger.critical("Нет доступных парсеров для запуска. Завершение работы.")
        sys.exit(1)

    # Инициализация менеджера объявлений
    data_dir = PROJECT_ROOT / 'data'
    data_dir.mkdir(exist_ok=True)
    state_file_path = data_dir / 'posted_listings.json'
    manager = ListingManager(state_file=state_file_path)
    logger.info(f"Менеджер объявлений инициализирован (файл состояния: {state_file_path}). Загружено {len(manager.seen_ids)} URL/ID.")

    # <<< Запускаем цикл один раз >>>
    try:
        await run_main_cycle(config, available_parsers, manager, proxy_list)
        logger.info("Однократный цикл проверки завершен.")
    except Exception as e:
        logger.critical(f"Критическая ошибка при однократном запуске цикла: {e}", exc_info=True)
    # <<< Конец однократного запуска >>>


# --- Точка входа --- (ВОССТАНОВЛЕННАЯ)
if __name__ == "__main__":
    try:
         asyncio.run(main())
    except KeyboardInterrupt:
         print("\nЗавершение работы по команде пользователя (Ctrl+C)")
         try:
             data_dir = PROJECT_ROOT / 'data'
             state_file_path = data_dir / 'posted_listings.json'
             temp_manager = ListingManager(state_file=state_file_path) 
             temp_manager._save_state() 
             print("Состояние менеджера объявлений сохранено.")
         except Exception as save_err:
             print(f"Не удалось сохранить состояние менеджера при выходе: {save_err}")
         sys.exit(0)
    except Exception as e:
         print(f"Непредвиденная ошибка на верхнем уровне: {e}")
         import traceback
         traceback.print_exc()
         sys.exit(1)