#!/usr/bin/env python3
"""
Модуль для управления прокси-серверами и их ротации.
Обеспечивает бесперебойный доступ к сайтам путем переключения между прокси.
"""

import os
import random
import logging
import time
import json
import re
import asyncio
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import aiohttp
import hashlib

# Устанавливаем logger для модуля
logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Класс для управления пулом прокси-серверов, их тестирования и ротации.
    """
    
    def __init__(self, 
                 proxy_file: Optional[str] = None,
                 proxy_list: Optional[List[str]] = None,
                 country_code: str = 'UY',
                 test_url: str = 'https://httpbin.org/ip',
                 max_failures: int = 3,
                 cache_dir: str = 'proxy_cache'):
        """
        Инициализирует менеджер прокси.
        
        Args:
            proxy_file: Путь к файлу со списком прокси
            proxy_list: Список прокси URL в формате protocol://user:pass@host:port
            country_code: Код страны для геофильтрации (если доступно)
            test_url: URL для проверки работоспособности прокси
            max_failures: Максимальное количество последовательных ошибок перед отключением прокси
            cache_dir: Директория для кэширования статистики прокси
        """
        self.country_code = country_code
        self.test_url = test_url
        self.max_failures = max_failures
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Структуры для хранения данных о прокси
        self.proxy_list: List[Dict[str, Any]] = []
        self.active_proxies: List[Dict[str, Any]] = []
        self.current_proxy_index = 0
        self.smartproxy_config = {}
        
        # Инициализируем список прокси
        if proxy_file:
            self.load_from_file(proxy_file)
        elif proxy_list:
            self.set_proxy_list(proxy_list)
        
        # Загружаем кэш статистики, если есть
        self.load_cache()
        
        logger.info(f"Инициализирован ProxyManager с {len(self.proxy_list)} прокси")

    def load_from_file(self, file_path: str) -> bool:
        """
        Загружает список прокси из файла.
        
        Args:
            file_path: Путь к файлу со списком прокси
            
        Returns:
            bool: True если загрузка успешна
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.error(f"Файл прокси не найден: {file_path}")
                return False
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
            
            # Конвертируем строки в структурированные данные о прокси
            proxy_list = []
            for line in lines:
                try:
                    # Преобразуем строку в URL прокси если это просто host:port
                    if not line.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
                        if ':' in line and '@' not in line:
                            line = f"http://{line}"
                        else:
                            logger.warning(f"Пропуск некорректного прокси: {line}")
                            continue
                    
                    proxy_info = self._parse_proxy_url(line)
                    if proxy_info:
                        proxy_list.append(proxy_info)
                except Exception as e:
                    logger.warning(f"Ошибка при обработке прокси {line}: {e}")
            
            self.set_proxy_list(proxy_list)
            logger.info(f"Загружено {len(self.proxy_list)} прокси из файла {file_path}")
            return bool(self.proxy_list)
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке прокси из файла {file_path}: {e}")
            return False

    def set_proxy_list(self, proxies: List[Any]) -> None:
        """
        Устанавливает список прокси из предоставленного списка.
        
        Args:
            proxies: Список прокси (строки URL или словари)
        """
        self.proxy_list = []
        
        for proxy in proxies:
            if isinstance(proxy, str):
                # Если proxy - строка URL, разбираем её
                proxy_info = self._parse_proxy_url(proxy)
                if proxy_info:
                    self.proxy_list.append(proxy_info)
            elif isinstance(proxy, dict) and 'url' in proxy:
                # Если словарь с полем url, используем как есть
                if 'failures' not in proxy:
                    proxy['failures'] = 0
                if 'success' not in proxy:
                    proxy['success'] = 0
                if 'last_used' not in proxy:
                    proxy['last_used'] = None
                if 'avg_response_time' not in proxy:
                    proxy['avg_response_time'] = None
                self.proxy_list.append(proxy)
            else:
                logger.warning(f"Пропуск некорректного формата прокси: {proxy}")
        
        # Фильтруем активные прокси
        self.refresh_active_proxies()

    def _parse_proxy_url(self, proxy_url: str) -> Optional[Dict[str, Any]]:
        """
        Разбирает URL прокси на компоненты.
        
        Args:
            proxy_url: URL прокси в формате protocol://[user:pass@]host:port
            
        Returns:
            Optional[Dict[str, Any]]: Словарь с данными о прокси или None в случае ошибки
        """
        try:
            # Проверяем формат URL
            url_pattern = r'^(http|https|socks5|socks4)://(?:([^:@]+):([^@]+)@)?([^:/]+):(\d+)/?$'
            match = re.match(url_pattern, proxy_url)
            
            if not match:
                logger.warning(f"Некорректный формат URL прокси: {proxy_url}")
                return None
            
            protocol, username, password, host, port = match.groups()
            
            # Создаем словарь с информацией о прокси
            proxy_info = {
                'url': proxy_url,
                'protocol': protocol,
                'host': host,
                'port': int(port),
                'username': username,
                'password': password,
                'failures': 0,
                'success': 0,
                'last_used': None,
                'last_checked': None,
                'avg_response_time': None,
                'country': None,
                'is_active': True
            }
            
            return proxy_info
        except Exception as e:
            logger.warning(f"Ошибка при разборе URL прокси {proxy_url}: {e}")
            return None

    def refresh_active_proxies(self) -> None:
        """
        Обновляет список активных прокси на основе критериев.
        """
        self.active_proxies = [
            proxy for proxy in self.proxy_list 
            if proxy.get('is_active', True) and proxy.get('failures', 0) < self.max_failures
        ]
        
        if not self.active_proxies and self.proxy_list:
            # Если нет активных прокси, сбрасываем счетчики ошибок и пробуем снова
            logger.warning("Нет активных прокси. Сбрасываем счетчики ошибок.")
            for proxy in self.proxy_list:
                proxy['failures'] = 0
                proxy['is_active'] = True
            self.active_proxies = list(self.proxy_list)
        
        logger.info(f"Активных прокси: {len(self.active_proxies)}/{len(self.proxy_list)}")

    async def test_all_proxies(self, concurrent: int = 5) -> List[Dict[str, Any]]:
        """
        Тестирует все прокси на работоспособность.
        
        Args:
            concurrent: Количество одновременных проверок
            
        Returns:
            List[Dict[str, Any]]: Список работающих прокси
        """
        # Создаем семафор для ограничения числа одновременных проверок
        semaphore = asyncio.Semaphore(concurrent)
        
        # Задачи для проверки каждого прокси
        tasks = []
        
        for proxy in self.proxy_list:
            task = asyncio.create_task(self._test_proxy_with_semaphore(proxy, semaphore))
            tasks.append(task)
        
        # Ждем завершения всех задач
        results = await asyncio.gather(*tasks)
        
        # Обновляем список активных прокси
        self.refresh_active_proxies()
        
        # Сохраняем кэш
        self.save_cache()
        
        return [proxy for proxy, success in zip(self.proxy_list, results) if success]

    async def _test_proxy_with_semaphore(self, proxy: Dict[str, Any], semaphore: asyncio.Semaphore) -> bool:
        """
        Тестирует прокси с использованием семафора для ограничения количества одновременных запросов.
        
        Args:
            proxy: Словарь с информацией о прокси
            semaphore: Семафор для ограничения конкурентности
            
        Returns:
            bool: True если прокси работает
        """
        async with semaphore:
            return await self.test_proxy(proxy)

    async def test_proxy(self, proxy: Dict[str, Any]) -> bool:
        """
        Проверяет работоспособность отдельного прокси.
        
        Args:
            proxy: Словарь с информацией о прокси
            
        Returns:
            bool: True если прокси работает
        """
        proxy_url = proxy['url']
        logger.debug(f"Тестирование прокси: {proxy_url}")
        
        try:
            # Определяем настройки aiohttp в зависимости от типа прокси
            connector = None
            proxies = None
            
            if proxy['protocol'] in ['socks4', 'socks5']:
                # Для SOCKS требуется специальный коннектор
                try:
                    from aiohttp_socks import ProxyConnector
                    connector = ProxyConnector.from_url(proxy_url)
                    proxies = None
                except ImportError:
                    logger.error("Для SOCKS прокси установите aiohttp_socks: pip install aiohttp_socks")
                    return False
            else:
                # Для HTTP прокси используем стандартные настройки
                proxies = proxy_url
            
            start_time = time.time()
            
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(self.test_url, proxy=proxies, timeout=15) as response:
                    if response.status == 200:
                        # Успешное соединение
                        response_time = time.time() - start_time
                        
                        # Обновляем информацию о прокси
                        proxy['failures'] = 0
                        proxy['success'] += 1
                        proxy['last_checked'] = datetime.now().isoformat()
                        
                        # Обновляем среднее время отклика
                        if proxy['avg_response_time'] is None:
                            proxy['avg_response_time'] = response_time
                        else:
                            proxy['avg_response_time'] = (proxy['avg_response_time'] * 0.7) + (response_time * 0.3)
                        
                        # Пытаемся определить страну
                        try:
                            json_response = await response.json()
                            proxy_ip = json_response.get('origin') or json_response.get('ip', '')
                            logger.debug(f"Прокси {proxy_url} работает. IP: {proxy_ip}, время: {response_time:.2f}s")
                            
                            # В дальнейшем тут можно добавить определение страны по IP
                            
                        except Exception as json_err:
                            logger.debug(f"Не удалось разобрать JSON от {self.test_url}: {json_err}")
                        
                        return True
                    else:
                        logger.debug(f"Прокси {proxy_url} вернул статус: {response.status}")
                        proxy['failures'] += 1
                        proxy['last_checked'] = datetime.now().isoformat()
                        return False
                    
        except Exception as e:
            logger.debug(f"Ошибка при проверке прокси {proxy_url}: {e}")
            proxy['failures'] += 1
            proxy['last_checked'] = datetime.now().isoformat()
            return False
        finally:
            # Закрываем connector, если он был создан
            if connector:
                await connector.close()

    def get_next_proxy(self) -> Optional[Dict[str, Any]]:
        """
        Возвращает следующий прокси из списка активных по принципу round-robin.
        
        Returns:
            Optional[Dict[str, Any]]: Следующий прокси или None, если нет активных
        """
        if not self.active_proxies:
            self.refresh_active_proxies()
            if not self.active_proxies:
                logger.warning("Нет активных прокси для использования")
                return None
        
        # Берем следующий прокси по кругу
        proxy = self.active_proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.active_proxies)
        
        # Обновляем время последнего использования
        proxy['last_used'] = datetime.now().isoformat()
        
        logger.debug(f"Выбран прокси: {proxy['url']}")
        return proxy

    def get_best_proxy(self) -> Optional[Dict[str, Any]]:
        """
        Возвращает лучший прокси на основе времени отклика и надежности.
        
        Returns:
            Optional[Dict[str, Any]]: Лучший прокси или None, если нет активных
        """
        if not self.active_proxies:
            self.refresh_active_proxies()
            if not self.active_proxies:
                logger.warning("Нет активных прокси для использования")
                return None
        
        # Сортируем прокси по соотношению успехов/ошибок и времени отклика
        def proxy_score(p):
            success_rate = p.get('success', 0) / (p.get('success', 0) + p.get('failures', 0) + 0.1)
            response_time = p.get('avg_response_time', 10.0)  # Если нет данных, предполагаем худшее
            if response_time is None:
                response_time = 10.0  # Если None, устанавливаем значение по умолчанию
            return success_rate / (response_time + 0.1)  # +0.1 для избежания деления на 0
        
        sorted_proxies = sorted(self.active_proxies, key=proxy_score, reverse=True)
        best_proxy = sorted_proxies[0]
        
        # Обновляем время последнего использования
        best_proxy['last_used'] = datetime.now().isoformat()
        
        logger.debug(f"Выбран лучший прокси: {best_proxy['url']}")
        return best_proxy

    def get_random_proxy(self) -> Optional[Dict[str, Any]]:
        """
        Возвращает случайный прокси из активных.
        
        Returns:
            Optional[Dict[str, Any]]: Случайный прокси или None, если нет активных
        """
        if not self.active_proxies:
            self.refresh_active_proxies()
            if not self.active_proxies:
                logger.warning("Нет активных прокси для использования")
                return None
        
        # Выбираем случайный прокси
        proxy = random.choice(self.active_proxies)
        
        # Обновляем время последнего использования
        proxy['last_used'] = datetime.now().isoformat()
        
        logger.debug(f"Выбран случайный прокси: {proxy['url']}")
        return proxy

    def mark_proxy_failed(self, proxy_url: str) -> None:
        """
        Отмечает прокси как неудачный, увеличивая счетчик ошибок.
        
        Args:
            proxy_url: URL прокси
        """
        for proxy in self.proxy_list:
            if proxy['url'] == proxy_url:
                proxy['failures'] += 1
                logger.debug(f"Прокси {proxy_url} отмечен как неудачный. Ошибок: {proxy['failures']}")
                
                # Отключаем прокси, если превышен лимит ошибок
                if proxy['failures'] >= self.max_failures:
                    proxy['is_active'] = False
                    logger.warning(f"Прокси {proxy_url} деактивирован после {proxy['failures']} ошибок")
                
                # Обновляем список активных прокси
                self.refresh_active_proxies()
                self.save_cache()
                return

    def mark_proxy_success(self, proxy_url: str) -> None:
        """
        Отмечает прокси как успешный, увеличивая счетчик успехов.
        
        Args:
            proxy_url: URL прокси
        """
        for proxy in self.proxy_list:
            if proxy['url'] == proxy_url:
                proxy['failures'] = max(0, proxy['failures'] - 1)  # Уменьшаем счетчик ошибок
                proxy['success'] += 1
                logger.debug(f"Прокси {proxy_url} отмечен как успешный. Успехов: {proxy['success']}")
                self.save_cache()
                return

    def load_cache(self) -> None:
        """
        Загружает кэшированную статистику использования прокси.
        """
        cache_file = self.cache_dir / 'proxy_stats.json'
        if not cache_file.exists():
            return
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_stats = json.load(f)
            
            # Обновляем информацию о прокси из кэша
            for proxy in self.proxy_list:
                proxy_url = proxy['url']
                if proxy_url in cached_stats:
                    stats = cached_stats[proxy_url]
                    proxy['failures'] = stats.get('failures', 0)
                    proxy['success'] = stats.get('success', 0)
                    proxy['last_used'] = stats.get('last_used')
                    proxy['last_checked'] = stats.get('last_checked')
                    proxy['avg_response_time'] = stats.get('avg_response_time')
                    proxy['country'] = stats.get('country')
                    proxy['is_active'] = stats.get('is_active', True)
            
            logger.debug(f"Загружена статистика для {len(cached_stats)} прокси")
        except Exception as e:
            logger.warning(f"Ошибка при загрузке кэша прокси: {e}")

    def save_cache(self) -> None:
        """
        Сохраняет статистику использования прокси в кэш.
        """
        cache_file = self.cache_dir / 'proxy_stats.json'
        
        try:
            # Создаем словарь для хранения статистики
            stats = {}
            for proxy in self.proxy_list:
                stats[proxy['url']] = {
                    'failures': proxy.get('failures', 0),
                    'success': proxy.get('success', 0),
                    'last_used': proxy.get('last_used'),
                    'last_checked': proxy.get('last_checked'),
                    'avg_response_time': proxy.get('avg_response_time'),
                    'country': proxy.get('country'),
                    'is_active': proxy.get('is_active', True)
                }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2)
            
            logger.debug(f"Кэш прокси сохранен в {cache_file}")
        except Exception as e:
            logger.warning(f"Ошибка при сохранении кэша прокси: {e}")

    def get_smartproxy_config(self) -> Dict[str, str]:
        """
        Создает конфигурацию SmartProxy для парсеров на основе текущего прокси.
        
        Returns:
            Dict[str, str]: Конфигурация для передачи в парсер
        """
        proxy = self.get_best_proxy() or self.get_random_proxy()
        
        if not proxy:
            return {}
        
        if proxy['protocol'] in ['http', 'https']:
            server_url = f"{proxy['host']}:{proxy['port']}"
            
            smartproxy_config = {
                "server": server_url,
                "user_pattern": proxy.get('username', ''),
                "password": proxy.get('password', '')
            }
            
            self.smartproxy_config = smartproxy_config
            return smartproxy_config
        else:
            logger.warning(f"Протокол {proxy['protocol']} не поддерживается для SmartProxy")
            return {}

def get_proxy_manager(proxy_file: Optional[str] = None, proxy_list: Optional[List[str]] = None) -> ProxyManager:
    """
    Создает и настраивает менеджер прокси.
    
    Args:
        proxy_file: Путь к файлу со списком прокси
        proxy_list: Список прокси URL
        
    Returns:
        ProxyManager: Настроенный менеджер прокси
    """
    return ProxyManager(proxy_file=proxy_file, proxy_list=proxy_list)

# Пример использования
if __name__ == "__main__":
    # Настраиваем логирование
    logging.basicConfig(level=logging.INFO)
    
    # Создаем тестовый список прокси
    test_proxies = [
        "http://user:pass@proxy1.example.com:8080",
        "socks5://proxy2.example.com:1080",
        "http://proxy3.example.com:8080"
    ]
    
    # Инициализируем менеджер прокси
    manager = ProxyManager(proxy_list=test_proxies)
    
    # Запускаем тест
    async def test_manager():
        # Тестируем все прокси
        working_proxies = await manager.test_all_proxies()
        print(f"Работающих прокси: {len(working_proxies)}/{len(test_proxies)}")
        
        # Получаем прокси для использования
        best_proxy = manager.get_best_proxy()
        if best_proxy:
            print(f"Лучший прокси: {best_proxy['url']}")
        
        # Получаем конфигурацию для SmartProxy
        smartproxy_config = manager.get_smartproxy_config()
        print(f"SmartProxy конфигурация: {smartproxy_config}")
    
    # Запускаем тест
    asyncio.run(test_manager()) 