#!/usr/bin/env python3
"""
Скрипт для создания и валидации файла с прокси-серверами.
Позволяет проверить доступность прокси и сохранить работающие прокси в файл.
"""

import os
import sys
import re
import asyncio
import argparse
import logging
from typing import List, Dict, Optional, Tuple
import aiohttp
from tqdm import tqdm
import random
from datetime import datetime
from pathlib import Path

# Определяем корневую директорию проекта относительно текущего файла
PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"

# Создаем директорию логов, если она не существует
LOGS_DIR.mkdir(exist_ok=True)

# Настройка логирования
log_file_path = LOGS_DIR / "proxy_validation.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ProxyValidator")

# Сервисы для проверки IP
CHECK_IP_URLS = [
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "https://api.myip.com"
]

# Тестовые URL для проверки прокси
TEST_URLS = [
    "https://www.google.com",
    "https://www.example.com",
    "https://httpbin.org/get"
]

def parse_proxy_url(proxy_url: str) -> Tuple[str, Optional[Dict[str, str]], str, str]:
    """
    Парсит URL прокси в компоненты.
    
    Args:
        proxy_url: URL прокси в формате 'protocol://[user:pass@]host:port'
        
    Returns:
        Tuple из протокола, авторизации, хоста и порта
    """
    # Проверяем формат URL
    url_pattern = r'^(http|https|socks5|socks4)://(?:([^:@]+):([^@]+)@)?([^:/]+):(\d+)/?$'
    match = re.match(url_pattern, proxy_url)
    
    if not match:
        raise ValueError(f"Некорректный формат URL прокси: {proxy_url}")
    
    protocol, username, password, host, port = match.groups()
    
    # Создаем словарь авторизации, если указаны логин и пароль
    auth = None
    if username and password:
        # Для aiohttp BasicAuth требуется в виде объекта
        auth = {'proxy_auth': aiohttp.BasicAuth(username, password)}
    
    return protocol, auth, host, port

async def check_proxy(session: aiohttp.ClientSession, proxy_url: str, timeout: int = 10) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    Проверяет работоспособность прокси.
    
    Args:
        session: Сессия aiohttp
        proxy_url: URL прокси
        timeout: Таймаут в секундах
        
    Returns:
        Tuple из флага успеха, IP-адреса и задержки
    """
    ip = None
    latency = None
    is_working = False
    start_time = asyncio.get_event_loop().time()
    
    try:
        protocol, auth, host, port = parse_proxy_url(proxy_url)
        
        # Используем connector для поддержки SOCKS и авторизации
        connector = None
        if protocol.startswith('socks'):
            try:
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(proxy_url)
            except ImportError:
                 logger.error("Для поддержки SOCKS прокси установите aiohttp_socks: pip install aiohttp_socks")
                 return False, None, None
        
        # Формируем proxy_url для session.get, если не SOCKS
        get_proxy_url = proxy_url if not connector else None
        
        # Настройки таймаута
        request_timeout = aiohttp.ClientTimeout(total=timeout)

        # 1. Проверяем основную функциональность (доступ к тестовому сайту)
        test_url = random.choice(TEST_URLS)
        async with session.get(test_url, proxy=get_proxy_url, connector=connector, timeout=request_timeout, ssl=False) as response:
            if response.status != 200:
                logger.debug(f"Прокси {proxy_url} не прошел тест доступа к {test_url} (статус: {response.status})")
                return False, None, None
        
        # 2. Проверяем IP-адрес
        check_url = random.choice(CHECK_IP_URLS)
        async with session.get(check_url, proxy=get_proxy_url, connector=connector, timeout=request_timeout, ssl=False) as response:
            if response.status != 200:
                 logger.debug(f"Прокси {proxy_url} не прошел тест получения IP с {check_url} (статус: {response.status})")
                 return False, None, None
            
            try: 
                data = await response.json()
                ip = data.get('ip') or data.get('origin') or data.get('query')
            except aiohttp.ContentTypeError:
                 # Если ответ не JSON, пытаемся извлечь IP из текста
                 text_response = await response.text()
                 ip_match = re.search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', text_response)
                 ip = ip_match.group(0) if ip_match else None
            except Exception as json_err:
                 logger.debug(f"Ошибка парсинга JSON от {check_url} через {proxy_url}: {json_err}")
                 return False, None, None

            if not ip:
                logger.debug(f"Не удалось извлечь IP с {check_url} через {proxy_url}")
                return False, None, None
            
            end_time = asyncio.get_event_loop().time()
            latency = int((end_time - start_time) * 1000)  # в миллисекундах
            is_working = True
            
            # 3. Убеждаемся, что IP отличается от локального (опционально, может замедлять)
            # try:
            #     async with session.get(check_url, timeout=request_timeout) as local_response:
            #         local_data = await local_response.json()
            #         local_ip = local_data.get('ip') or local_data.get('origin') or local_data.get('query')
            #         if ip == local_ip:
            #             logger.warning(f"Прокси {proxy_url} не меняет IP-адрес (локальный: {local_ip})")
            #             is_working = False # Считаем такой прокси нерабочим для наших целей
            # except Exception as local_ip_err:
            #      logger.warning(f"Не удалось получить локальный IP для сравнения: {local_ip_err}")
                
            return is_working, ip, latency
            
    except asyncio.TimeoutError:
        logger.debug(f"Прокси {proxy_url} превысил таймаут ({timeout}c)")
        return False, None, None
    except aiohttp.ClientProxyConnectionError as proxy_err:
         logger.debug(f"Ошибка соединения с прокси {proxy_url}: {proxy_err}")
         return False, None, None
    except Exception as e:
        logger.debug(f"Неизвестная ошибка при проверке прокси {proxy_url}: {e}")
        # traceback.print_exc() # Раскомментировать для детальной отладки
        return False, None, None
    finally:
        # Важно закрывать connector, если он был создан
        if connector:
            await connector.close()

async def validate_proxies(proxy_list: List[str], max_concurrent: int = 10, timeout: int = 10) -> List[Dict[str, Any]]:
    """
    Проверяет список прокси на работоспособность.
    
    Args:
        proxy_list: Список URL прокси
        max_concurrent: Максимальное количество одновременных проверок
        timeout: Таймаут для каждого прокси в секундах
        
    Returns:
        Список словарей с информацией о работающих прокси
    """
    working_proxies = []
    
    # Создаем семафор для ограничения количества одновременных запросов
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def check_with_semaphore(proxy_url):
        async with semaphore:
            # Создаем сессию внутри, чтобы избежать проблем с переиспользованием
            async with aiohttp.ClientSession() as session:
                success, ip, latency = await check_proxy(session, proxy_url, timeout)
                if success:
                    return {
                        "url": proxy_url,
                        "ip": ip,
                        "latency": latency
                    }
                return None
    
    # Запускаем проверку всех прокси
    print(f"Проверка {len(proxy_list)} прокси (макс. одновременно: {max_concurrent}, таймаут: {timeout}с)...")
    
    tasks = [check_with_semaphore(proxy) for proxy in proxy_list]
    
    # Отображаем прогресс с помощью tqdm
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Проверка прокси"):
        proxy_info = await f
        if proxy_info:
            working_proxies.append(proxy_info)
            logger.info(f"Рабочий прокси: {proxy_info['url']} (IP: {proxy_info['ip']}, задержка: {proxy_info['latency']}мс)")
    
    return working_proxies

def load_proxies_from_file(file_path: str) -> List[str]:
    """
    Загружает список прокси из файла.
    
    Args:
        file_path: Путь к файлу с прокси
        
    Returns:
        Список URL прокси
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Файл не найден: {file_path}")
    
    proxies = set() # Используем set для автоматической дедупликации
    with open(file_path, 'r') as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    
    # Проверяем формат каждого прокси
    valid_proxies = []
    for line in lines:
        try:
            # Если строка содержит только host:port, добавляем http://
            if not re.match(r'^(http|https|socks5|socks4)://', line):
                if ':' in line and '@' not in line.split(':')[0]: # Простая проверка на host:port
                     line = f"http://{line}"
                else:
                     raise ValueError("Непонятный формат строки, ожидается protocol://[user:pass@]host:port или host:port")
            
            # Проверяем, что URL соответствует паттерну
            parse_proxy_url(line)
            proxies.add(line)
        except ValueError as e:
            logger.warning(f"Пропускаем некорректный прокси: '{line}' - {e}")
    
    logger.info(f"Загружено {len(proxies)} уникальных прокси из файла.")
    return list(proxies)

def save_proxies_to_file(proxies: List[Dict[str, Any]], output_file: str):
    """
    Сохраняет список прокси в файл.
    
    Args:
        proxies: Список словарей с информацией о прокси
        output_file: Путь к файлу для сохранения
    """
    # Сортируем по задержке перед сохранением
    sorted_proxies = sorted(proxies, key=lambda x: x.get('latency', float('inf')))
    
    output_path = Path(output_file)
    # Создаем директорию, если она не существует
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        f.write(f"# Список проверенных рабочих прокси для UruguayLands\n")
        f.write(f"# Всего найдено: {len(sorted_proxies)}\n")
        f.write(f"# Формат: URL прокси (сортировка по задержке)\n")
        f.write(f"# Создан: {datetime.now().isoformat()}\n\n")
        
        for proxy in sorted_proxies:
            # Сохраняем только URL прокси
            f.write(f"{proxy['url']}\n")
            # Добавляем комментарий с деталями (опционально)
            # f.write(f"{proxy['url']} # IP: {proxy['ip']}, Задержка: {proxy['latency']}мс\n")

def generate_sample_proxies(output_dir="."):
    """
    Генерирует пример файла с прокси.
    """
    sample_file = Path(output_dir) / "proxy_example.txt"
    sample_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(sample_file, 'w') as f:
        f.write("# Пример списка прокси для UruguayLands\n")
        f.write("# Формат: протокол://[пользователь:пароль@]хост:порт ИЛИ хост:порт (будет использован http)\n")
        f.write("# Поддерживаемые протоколы: http, https, socks4, socks5 (требуется pip install aiohttp_socks)\n\n")
        
        f.write("# Примеры HTTP прокси\n")
        f.write("192.168.1.1:8080\n")
        f.write("http://user:password@192.168.1.2:8080\n\n")
        
        f.write("# Примеры HTTPS прокси\n")
        f.write("https://192.168.1.3:8443\n")
        f.write("https://user:password@192.168.1.4:8443\n\n")
        
        f.write("# Примеры SOCKS прокси\n")
        f.write("socks5://192.168.1.5:1080\n")
        f.write("socks4://user:password@192.168.1.6:1080\n")
    
    print(f"Создан пример файла с прокси: {sample_file}")

async def main():
    parser = argparse.ArgumentParser(description="Проверка и валидация прокси-серверов для UruguayLands",
                                     formatter_class=argparse.RawTextHelpFormatter)
    
    # Обязательный аргумент с файлом прокси или опцией примера
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--file', '-f', type=str, 
                       help='Путь к файлу со списком прокси.\nКаждая строка - один прокси в формате protocol://[user:pass@]host:port или host:port.')
    group.add_argument('--example', '-e', action='store_true', 
                       help='Создать пример файла proxy_example.txt в текущей директории.')
    
    # Дополнительные аргументы
    parser.add_argument('--output', '-o', type=str, 
                       help='Путь для сохранения файла с работающими прокси.\nПо умолчанию: working_proxies_[исходное_имя].txt')
    parser.add_argument('--timeout', '-t', type=int, default=10, 
                       help='Таймаут для проверки каждого прокси (секунды, по умолчанию: 10)')
    parser.add_argument('--concurrent', '-c', type=int, default=20, 
                       help='Макс. количество одновременных проверок (по умолчанию: 20)')
    
    args = parser.parse_args()
    
    if args.example:
        generate_sample_proxies()
        return
    
    try:
        # Загружаем прокси из файла
        proxies_to_check = load_proxies_from_file(args.file)
        
        if not proxies_to_check:
            logger.error("Не найдено корректных прокси в файле для проверки.")
            return
        
        # Валидируем прокси
        start_validation_time = datetime.now()
        working_proxies = await validate_proxies(
            proxies_to_check, 
            max_concurrent=args.concurrent, 
            timeout=args.timeout
        )
        validation_duration = datetime.now() - start_validation_time
        logger.info(f"Проверка завершена за {validation_duration}")
        
        # Выводим результаты
        if working_proxies:
            logger.info(f"Найдено {len(working_proxies)} работающих прокси из {len(proxies_to_check)} проверенных.")
            
            # Если не указан выходной файл, используем имя входного с префиксом 'working_'
            output_file = args.output
            if not output_file:
                input_filename = Path(args.file).stem
                output_file = f"working_proxies_{input_filename}.txt"
            
            # Сохраняем работающие прокси
            save_proxies_to_file(working_proxies, output_file)
            logger.info(f"Работающие прокси (только URL) сохранены в файл: {output_file}")
            
            # Выводим топ-5 прокси по скорости
            print("\nТоп-5 самых быстрых прокси:")
            for i, proxy in enumerate(working_proxies[:5], 1):
                print(f"{i}. {proxy['url']} - Задержка: {proxy['latency']}мс, IP: {proxy['ip']}")
        else:
            logger.error("Рабочие прокси не найдены.")
    
    except FileNotFoundError as e:
        logger.error(f"Ошибка: Файл не найден - {e}")
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Для поддержки SOCKS на Windows может потребоваться
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПроверка прервана пользователем")
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc() 