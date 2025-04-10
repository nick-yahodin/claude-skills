#!/usr/bin/env python3
"""
Модуль для эмуляции браузеров и управления отпечатками браузера.
Позволяет имитировать различные браузеры и устройства для обхода блокировок.
"""

import os
import json
import random
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import hashlib

# Устанавливаем logger для модуля
logger = logging.getLogger(__name__)

# Пути для хранения сохраненных профилей
PROFILES_DIR = Path("browser_profiles")
PROFILES_DIR.mkdir(exist_ok=True)

class BrowserEmulator:
    """
    Класс для эмуляции различных браузеров и устройств.
    Генерирует реалистичные browser fingerprints для обхода блокировок.
    """
    
    # Стандартные платформы и их характеристики
    PLATFORMS = {
        'Windows': {
            'os': ['Windows NT 10.0', 'Windows NT 10.0; Win64; x64'],
            'browsers': ['Chrome', 'Firefox', 'Edge'],
            'versions': {
                'Chrome': ['112.0.0.0', '113.0.0.0', '114.0.0.0', '115.0.0.0'],
                'Firefox': ['112.0', '113.0', '114.0', '115.0'],
                'Edge': ['112.0.1722.58', '113.0.1774.50', '114.0.1823.67']
            }
        },
        'Mac': {
            'os': ['Macintosh; Intel Mac OS X 10_15_7', 'Macintosh; Intel Mac OS X 11_0_0'],
            'browsers': ['Chrome', 'Firefox', 'Safari'],
            'versions': {
                'Chrome': ['112.0.0.0', '113.0.0.0', '114.0.0.0', '115.0.0.0'],
                'Firefox': ['112.0', '113.0', '114.0', '115.0'],
                'Safari': ['15.6.1', '16.0', '16.2', '16.5']
            }
        },
        'Linux': {
            'os': ['X11; Linux x86_64', 'X11; Ubuntu; Linux x86_64'],
            'browsers': ['Chrome', 'Firefox'],
            'versions': {
                'Chrome': ['112.0.0.0', '113.0.0.0', '114.0.0.0', '115.0.0.0'],
                'Firefox': ['112.0', '113.0', '114.0', '115.0']
            }
        }
    }
    
    # Области экрана
    VIEWPORTS = [
        {'width': 1366, 'height': 768},   # Распространенное разрешение ноутбуков
        {'width': 1440, 'height': 900},   # Macbook
        {'width': 1536, 'height': 864},   # Распространенное разрешение
        {'width': 1920, 'height': 1080},  # Full HD
        {'width': 2560, 'height': 1440}   # 2K
    ]
    
    # Языки для эмуляции
    LANGUAGES = [
        ['es-ES', 'es', 'en-US', 'en'],   # Испанский (Испания), Английский (США)
        ['es-UY', 'es-419', 'es', 'en'],  # Испанский (Уругвай, Латинская Америка)
        ['en-US', 'en', 'es'],            # Английский (США), Испанский
    ]
    
    # WebGL производители
    WEBGL_VENDORS = [
        'Google Inc. (Intel)',
        'Google Inc. (NVIDIA)',
        'Google Inc. (AMD)',
        'Google Inc. (ATI)',
        'Mozilla',
        'Apple Inc.'
    ]
    
    # Возможные плагины
    PLUGINS = [
        'Chrome PDF Plugin',
        'Chrome PDF Viewer',
        'Native Client',
        'Widevine Content Decryption Module',
        'Google Drive',
        'Adobe Acrobat'
    ]
    
    def __init__(self, country_code: str = 'UY', use_real_browsers: bool = False):
        """
        Инициализирует эмулятор браузера.
        
        Args:
            country_code: Код страны для геолокации (по умолчанию Уругвай)
            use_real_browsers: Использовать ли настоящие профили браузеров
        """
        self.country_code = country_code
        self.use_real_browsers = use_real_browsers
        self.cached_profiles = {}
        self.load_country_coordinates()
        
    def load_country_coordinates(self):
        """Загружает координаты для эмуляции геолокации в указанной стране."""
        # Координаты центров крупных городов Уругвая
        self.URUGUAY_COORDS = [
            {'latitude': -34.9011, 'longitude': -56.1915, 'city': 'Montevideo'},
            {'latitude': -34.7666, 'longitude': -55.7577, 'city': 'Punta del Este'},
            {'latitude': -34.4626, 'longitude': -57.8400, 'city': 'Colonia del Sacramento'},
            {'latitude': -32.3158, 'longitude': -58.0797, 'city': 'Paysandú'},
            {'latitude': -33.3874, 'longitude': -56.5155, 'city': 'Florida'}
        ]
        
        # Можно добавить координаты и для других стран
        self.COUNTRY_COORDS = {
            'UY': self.URUGUAY_COORDS,
            # Добавить другие страны при необходимости
        }
    
    def generate_fingerprint(self, seed: Optional[str] = None) -> Dict[str, Any]:
        """
        Генерирует реалистичный отпечаток браузера.
        
        Args:
            seed: Опциональное начальное значение для генератора случайных чисел
        
        Returns:
            Dict[str, Any]: Словарь с параметрами отпечатка браузера
        """
        # Устанавливаем seed для получения воспроизводимых результатов, если он задан
        if seed:
            random.seed(seed)
        
        # Выбор случайной платформы
        platform = random.choice(list(self.PLATFORMS.keys()))
        os_info = random.choice(self.PLATFORMS[platform]['os'])
        browser = random.choice(self.PLATFORMS[platform]['browsers'])
        browser_version = random.choice(self.PLATFORMS[platform]['versions'][browser])
        
        # Генерация user-agent на основе платформы и браузера
        user_agent = self._generate_user_agent(platform, os_info, browser, browser_version)
        
        # Выбор разрешения экрана
        viewport = random.choice(self.VIEWPORTS)
        
        # Выбор языков
        languages = random.choice(self.LANGUAGES)
        
        # Генерация геолокации
        country_coords = self.COUNTRY_COORDS.get(self.country_code, self.URUGUAY_COORDS)
        location = random.choice(country_coords)
        geolocation = {
            'latitude': location['latitude'] + random.uniform(-0.01, 0.01),
            'longitude': location['longitude'] + random.uniform(-0.01, 0.01),
            'accuracy': random.uniform(20, 100)
        }
        
        # Выбор WebGL vendor
        webgl_vendor = random.choice(self.WEBGL_VENDORS)
        
        # Генерация списка плагинов
        plugins_count = random.randint(2, 5)
        plugins = random.sample(self.PLUGINS, min(plugins_count, len(self.PLUGINS)))
        
        # Дополнительные параметры для отпечатка
        additional_params = {
            'deviceMemory': random.choice([2, 4, 8, 16]),
            'hardwareConcurrency': random.choice([2, 4, 6, 8, 12, 16]),
            'colorDepth': random.choice([24, 30, 32]),
            'pixelRatio': random.choice([1.0, 1.5, 2.0, 2.5]),
            'timezone': random.choice(['America/Montevideo', 'America/Buenos_Aires']),
            'doNotTrack': random.choice([None, 0, 1]),
            'canvasBlooming': random.choice([True, False]),  # Некоторые сайты проверяют рисование на canvas
            'audioContext': random.choice([True, False])     # Проверка поддержки AudioContext
        }
        
        # Сборка полного отпечатка
        fingerprint = {
            'userAgent': user_agent,
            'platform': platform,
            'browser': browser,
            'browserVersion': browser_version,
            'viewport': {
                'width': viewport['width'],
                'height': viewport['height'],
                'deviceScaleFactor': random.choice([1, 1.5, 2, 2.5]),
                'isMobile': False,
                'hasTouch': random.choice([False, False, False, True]),  # В основном desktop, но иногда touch
                'isLandscape': True
            },
            'languages': languages,
            'geolocation': geolocation,
            'webgl': {
                'vendor': webgl_vendor,
                'renderer': f"{webgl_vendor} WebGL {random.choice(['1.0', '2.0'])}"
            },
            'plugins': plugins,
            **additional_params
        }
        
        # Сброс seed, если он был установлен
        if seed:
            random.seed(None)
            
        return fingerprint
        
    def _generate_user_agent(self, platform: str, os_info: str, browser: str, version: str) -> str:
        """
        Генерирует user-agent на основе данных о платформе и браузере.
        
        Args:
            platform: Тип платформы (Windows, Mac, Linux)
            os_info: Строка с информацией об ОС
            browser: Тип браузера (Chrome, Firefox, Safari)
            version: Версия браузера
            
        Returns:
            str: User-agent строка
        """
        if browser == 'Chrome':
            return f"Mozilla/5.0 ({os_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
        elif browser == 'Firefox':
            return f"Mozilla/5.0 ({os_info}; rv:{version}) Gecko/20100101 Firefox/{version}"
        elif browser == 'Edge':
            return f"Mozilla/5.0 ({os_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36 Edg/{version}"
        elif browser == 'Safari':
            webkit_version = "605.1.15"
            return f"Mozilla/5.0 ({os_info}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Version/{version} Safari/{webkit_version}"
        
        # Если тип браузера не распознан, возвращаем Chrome
        return f"Mozilla/5.0 ({os_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
    
    def save_profile(self, fingerprint: Dict[str, Any], profile_name: Optional[str] = None) -> str:
        """
        Сохраняет отпечаток браузера в файл профиля.
        
        Args:
            fingerprint: Словарь с параметрами отпечатка
            profile_name: Опциональное имя профиля
            
        Returns:
            str: Имя созданного профиля
        """
        if not profile_name:
            # Генерируем имя на основе user-agent и текущего времени
            hash_base = f"{fingerprint['userAgent']}_{datetime.now().isoformat()}"
            profile_hash = hashlib.md5(hash_base.encode()).hexdigest()[:10]
            profile_name = f"profile_{profile_hash}"
        
        profile_path = PROFILES_DIR / f"{profile_name}.json"
        
        # Добавляем метаданные профиля
        profile_data = {
            "fingerprint": fingerprint,
            "metadata": {
                "created": datetime.now().isoformat(),
                "source": "browser_emulation.py",
                "version": "1.0"
            }
        }
        
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, indent=2)
            
        logger.debug(f"Профиль сохранен: {profile_path}")
        return profile_name
    
    def load_profile(self, profile_name: str) -> Optional[Dict[str, Any]]:
        """
        Загружает профиль браузера из файла.
        
        Args:
            profile_name: Имя профиля
            
        Returns:
            Optional[Dict[str, Any]]: Словарь с параметрами отпечатка или None, если профиль не найден
        """
        # Проверяем кэш
        if profile_name in self.cached_profiles:
            return self.cached_profiles[profile_name]
        
        # Проверяем расширение файла
        if not profile_name.endswith('.json'):
            profile_name = f"{profile_name}.json"
            
        profile_path = PROFILES_DIR / profile_name
        
        if not profile_path.exists():
            logger.warning(f"Профиль не найден: {profile_path}")
            return None
            
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
                
            fingerprint = profile_data.get("fingerprint", {})
            
            # Кэшируем для повторного использования
            self.cached_profiles[profile_name] = fingerprint
            
            return fingerprint
        except Exception as e:
            logger.error(f"Ошибка при загрузке профиля {profile_path}: {e}")
            return None
    
    def get_playwright_options(self, fingerprint: Dict[str, Any]) -> Dict[str, Any]:
        """
        Получает параметры для настройки Playwright на основе отпечатка.
        
        Args:
            fingerprint: Словарь с параметрами отпечатка
            
        Returns:
            Dict[str, Any]: Параметры для Playwright browser_context.new_page()
        """
        user_agent = fingerprint.get('userAgent', '')
        
        # Создаем параметры для передачи в context.new_page()
        playwright_options = {
            'user_agent': user_agent,
            'viewport': fingerprint.get('viewport', {'width': 1366, 'height': 768}),
            'locale': fingerprint.get('languages', ['es-UY'])[0],
            'timezone_id': fingerprint.get('timezone', 'America/Montevideo'),
            'geolocation': fingerprint.get('geolocation', None),
            'permissions': ['geolocation'],
            'is_mobile': fingerprint.get('viewport', {}).get('isMobile', False),
            'has_touch': fingerprint.get('viewport', {}).get('hasTouch', False),
            'color_scheme': 'light',  # Можно также использовать 'dark'
            'reduced_motion': 'no-preference',
            'forced_colors': 'none',
            'device_scale_factor': fingerprint.get('viewport', {}).get('deviceScaleFactor', 1),
            'bypass_csp': True,  # Обход Content Security Policy
            'java_script_enabled': True,  # Всегда включаем JavaScript
            'extra_http_headers': {
                'Accept-Language': fingerprint.get('languages', ['es-UY'])[0],
                'Sec-CH-UA': f'"Not.A/Brand";v="8", "Chromium";v="{fingerprint.get("browserVersion", "115.0.0.0")}"'
            }
        }
        
        return playwright_options
    
    def create_evasion_scripts(self, fingerprint: Dict[str, Any]) -> List[str]:
        """
        Создает JavaScript скрипты для обхода обнаружения автоматизации.
        
        Args:
            fingerprint: Словарь с параметрами отпечатка
            
        Returns:
            List[str]: Список JavaScript скриптов для выполнения на странице
        """
        # Скрипты для маскировки автоматизации
        evasion_scripts = []
        
        # 1. Маскировка navigator
        navigator_script = f"""
        Object.defineProperty(navigator, 'userAgent', {{ 
            get: () => '{fingerprint.get("userAgent")}' 
        }});
        Object.defineProperty(navigator, 'languages', {{ 
            get: () => {json.dumps(fingerprint.get("languages", ["es-UY"]))} 
        }});
        Object.defineProperty(navigator, 'deviceMemory', {{ 
            get: () => {fingerprint.get("deviceMemory", 8)} 
        }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ 
            get: () => {fingerprint.get("hardwareConcurrency", 8)} 
        }});
        Object.defineProperty(navigator, 'platform', {{ 
            get: () => '{fingerprint.get("platform", "Linux")}' 
        }});
        """
        evasion_scripts.append(navigator_script)
        
        # 2. Маскировка webdriver
        webdriver_script = """
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        if (navigator.plugins) {
            Object.defineProperty(navigator, 'plugins', {
                get: () => Array.from({length: 5}).fill().map(() => ({
                    name: 'Chrome PDF Plugin',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 1
                }))
            });
        }
        """
        evasion_scripts.append(webdriver_script)
        
        # 3. Маскировка функций автоматизации
        automation_script = """
        // Защита от обнаружения через console.debug
        const originalConsoleDebug = console.debug;
        console.debug = function(...args) {
            if (args.length > 0 && args[0].includes('headless')) {
                return; // Блокируем отладочные сообщения с "headless"
            }
            return originalConsoleDebug.apply(this, args);
        };
        
        // Защита от обнаружения через performance.now()
        const originalPerformance = performance;
        performance.now = function() {
            return originalPerformance.now() + (Math.random() * 5);
        };
        """
        evasion_scripts.append(automation_script)
        
        # 4. Защита от canvas fingerprinting
        canvas_script = """
        // Добавляем шум к canvas для затруднения идентификации
        const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
            const imageData = originalGetImageData.call(this, x, y, w, h);
            const pixels = imageData.data;
            
            // Добавляем незначительный шум к данным пикселей
            for (let i = 0; i < pixels.length; i += 4) {
                pixels[i] = pixels[i] + Math.floor(Math.random() * 5 - 2);     // r
                pixels[i+1] = pixels[i+1] + Math.floor(Math.random() * 5 - 2); // g
                pixels[i+2] = pixels[i+2] + Math.floor(Math.random() * 5 - 2); // b
            }
            
            return imageData;
        };
        """
        evasion_scripts.append(canvas_script)
        
        return evasion_scripts

def create_persistent_fingerprint(user_id: str) -> Dict[str, Any]:
    """
    Создает персистентный отпечаток для конкретного пользователя.
    Гарантирует, что для одного user_id всегда будет генерироваться 
    один и тот же отпечаток.
    
    Args:
        user_id: Идентификатор пользователя или сессии
        
    Returns:
        Dict[str, Any]: Словарь с параметрами отпечатка
    """
    # Создаем хеш из user_id для использования в качестве seed
    hash_obj = hashlib.md5(user_id.encode())
    seed = hash_obj.hexdigest()
    
    # Инициализируем эмулятор и генерируем отпечаток с указанным seed
    emulator = BrowserEmulator()
    fingerprint = emulator.generate_fingerprint(seed=seed)
    
    return fingerprint

def get_random_fingerprint() -> Dict[str, Any]:
    """
    Получает случайный отпечаток браузера.
    
    Returns:
        Dict[str, Any]: Словарь с параметрами отпечатка
    """
    emulator = BrowserEmulator()
    return emulator.generate_fingerprint()

def load_or_create_profile(profile_name: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """
    Загружает существующий профиль или создает новый.
    
    Args:
        profile_name: Опциональное имя профиля
        
    Returns:
        Tuple[Dict[str, Any], str]: Отпечаток и имя профиля
    """
    emulator = BrowserEmulator()
    
    if profile_name:
        fingerprint = emulator.load_profile(profile_name)
        if fingerprint:
            return fingerprint, profile_name
    
    # Если профиль не указан или не найден, создаем новый
    fingerprint = emulator.generate_fingerprint()
    new_profile_name = emulator.save_profile(fingerprint)
    
    return fingerprint, new_profile_name

# Пример использования
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Создаем эмулятор
    emulator = BrowserEmulator()
    
    # Генерируем новый случайный отпечаток
    fingerprint = emulator.generate_fingerprint()
    
    # Сохраняем отпечаток в профиль
    profile_name = emulator.save_profile(fingerprint)
    
    # Получаем параметры для Playwright
    playwright_options = emulator.get_playwright_options(fingerprint)
    
    # Выводим сгенерированный отпечаток
    print(f"Сгенерирован случайный отпечаток браузера в профиле: {profile_name}")
    print(f"User-Agent: {fingerprint['userAgent']}")
    print(f"Browser: {fingerprint['browser']} {fingerprint['browserVersion']}")
    print(f"Platform: {fingerprint['platform']}")
    print(f"Viewport: {fingerprint['viewport']['width']}x{fingerprint['viewport']['height']}")
    print(f"Languages: {fingerprint['languages']}")
    
    # Создаем скрипты уклонения от обнаружения
    evasion_scripts = emulator.create_evasion_scripts(fingerprint)
    print(f"Создано {len(evasion_scripts)} скриптов для обхода обнаружения") 