#!/usr/bin/env python3
"""
Модуль для обхода и решения CAPTCHA при парсинге сайтов.
Поддерживает как reCAPTCHA v2, так и v3.
"""

import os
import re
import time
import logging
import random
import base64
from typing import Dict, Optional, Tuple, Any, List
from pathlib import Path
import asyncio

from playwright.async_api import Page, ElementHandle

# Устанавливаем logger для модуля
logger = logging.getLogger(__name__)

# Пытаемся импортировать сервисы решения CAPTCHA
try:
    import anticaptchaofficial
    ANTICAPTCHA_AVAILABLE = True
except ImportError:
    ANTICAPTCHA_AVAILABLE = False
    logger.warning("AntiCaptcha API не установлен. Используйте: pip install anticaptchaofficial")

try:
    import twocaptcha
    TWOCAPTCHA_AVAILABLE = True
except ImportError:
    TWOCAPTCHA_AVAILABLE = False
    logger.warning("2Captcha API не установлен. Используйте: pip install 2captcha-python")

# API ключи для сервисов решения CAPTCHA
ANTICAPTCHA_KEY = os.environ.get("ANTICAPTCHA_KEY", "")
TWOCAPTCHA_KEY = os.environ.get("TWOCAPTCHA_KEY", "")

class CaptchaSolver:
    """
    Класс для обхода и решения CAPTCHA на веб-страницах.
    """
    def __init__(self, 
                 use_anticaptcha: bool = True, 
                 use_twocaptcha: bool = True, 
                 captcha_timeout: int = 60,
                 debug_mode: bool = False):
        """
        Инициализирует решатель CAPTCHA.
        
        Args:
            use_anticaptcha: Использовать AntiCaptcha (если доступно)
            use_twocaptcha: Использовать 2Captcha (если доступно)
            captcha_timeout: Таймаут для решения CAPTCHA в секундах
            debug_mode: Режим отладки (больше логов и скриншотов)
        """
        self.use_anticaptcha = use_anticaptcha and ANTICAPTCHA_AVAILABLE and ANTICAPTCHA_KEY
        self.use_twocaptcha = use_twocaptcha and TWOCAPTCHA_AVAILABLE and TWOCAPTCHA_KEY
        self.captcha_timeout = captcha_timeout
        self.debug_mode = debug_mode
        
        # Проверяем доступность любого решателя
        if not (self.use_anticaptcha or self.use_twocaptcha):
            logger.warning("Ни один сервис решения CAPTCHA не настроен. Решение CAPTCHA будет ограничено.")

    async def detect_captcha(self, page: Page) -> Dict[str, Any]:
        """
        Определяет наличие CAPTCHA на странице и её тип.
        
        Args:
            page: Объект страницы Playwright
            
        Returns:
            Dict[str, Any]: Информация о найденной CAPTCHA или пустой словарь
        """
        # Сохраняем скриншот в режиме отладки
        if self.debug_mode:
            debug_path = f"captcha_debug_{int(time.time())}.png"
            await page.screenshot(path=debug_path)
            logger.debug(f"Сохранен скриншот для проверки CAPTCHA: {debug_path}")
        
        captcha_info = {}
        
        # Проверяем наличие видимых элементов reCAPTCHA
        visible_captcha = await page.query_selector('div.g-recaptcha, iframe[src*="recaptcha"], div[class*="recaptcha"]')
        if visible_captcha:
            logger.info("Обнаружена видимая reCAPTCHA")
            captcha_info['type'] = 'recaptcha'
            captcha_info['visible'] = True
            
            # Определяем версию reCAPTCHA
            if await page.query_selector('div.g-recaptcha[data-size="invisible"]'):
                captcha_info['version'] = 'invisible'
            else:
                captcha_info['version'] = 'v2'
            
            # Получаем sitekey
            sitekey_element = await page.query_selector('div.g-recaptcha[data-sitekey]')
            if sitekey_element:
                sitekey = await sitekey_element.get_attribute('data-sitekey')
                captcha_info['sitekey'] = sitekey
            
            return captcha_info
            
        # Проверяем наличие reCAPTCHA v3
        html_content = await page.content()
        recaptcha_v3_match = re.search(r'grecaptcha\.execute\([\'"]([^\'"]+)[\'"]', html_content)
        if not recaptcha_v3_match:
            recaptcha_v3_match = re.search(r'recaptchaSiteKey[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]', html_content)
            
        if recaptcha_v3_match:
            logger.info("Обнаружена reCAPTCHA v3")
            captcha_info['type'] = 'recaptcha'
            captcha_info['visible'] = False
            captcha_info['version'] = 'v3'
            captcha_info['sitekey'] = recaptcha_v3_match.group(1)
            return captcha_info
        
        # Проверяем наличие Cloudflare CAPTCHA
        cloudflare_captcha = await page.query_selector('form[action*="cloudflare"]')
        if cloudflare_captcha:
            logger.info("Обнаружена Cloudflare CAPTCHA")
            captcha_info['type'] = 'cloudflare'
            captcha_info['visible'] = True
            return captcha_info
        
        logger.debug("CAPTCHA не обнаружена на странице")
        return captcha_info
    
    async def solve_recaptcha(self, page: Page, captcha_info: Dict[str, Any]) -> Optional[str]:
        """
        Решает reCAPTCHA на странице.
        
        Args:
            page: Объект страницы Playwright
            captcha_info: Информация о CAPTCHA
            
        Returns:
            Optional[str]: Токен решения CAPTCHA или None
        """
        page_url = page.url
        sitekey = captcha_info.get('sitekey')
        
        if not sitekey:
            logger.error("Отсутствует sitekey для решения reCAPTCHA")
            return None
        
        logger.info(f"Начинаем решение reCAPTCHA {captcha_info.get('version', 'v2')} на {page_url}")
        
        # Пробуем AntiCaptcha
        if self.use_anticaptcha:
            try:
                token = await self._solve_with_anticaptcha(page_url, sitekey, captcha_info.get('version', 'v2'))
                if token:
                    return token
            except Exception as e:
                logger.error(f"Ошибка при использовании AntiCaptcha: {e}")
        
        # Пробуем 2Captcha
        if self.use_twocaptcha:
            try:
                token = await self._solve_with_twocaptcha(page_url, sitekey, captcha_info.get('version', 'v2'))
                if token:
                    return token
            except Exception as e:
                logger.error(f"Ошибка при использовании 2Captcha: {e}")
        
        logger.error("Не удалось решить reCAPTCHA с помощью доступных сервисов")
        return None
    
    async def _solve_with_anticaptcha(self, page_url: str, sitekey: str, version: str) -> Optional[str]:
        """
        Решает reCAPTCHA с помощью AntiCaptcha.
        
        Args:
            page_url: URL страницы
            sitekey: Ключ сайта reCAPTCHA
            version: Версия reCAPTCHA
            
        Returns:
            Optional[str]: Токен решения или None
        """
        if not ANTICAPTCHA_AVAILABLE:
            return None
        
        logger.info(f"Решение reCAPTCHA через AntiCaptcha: {page_url}, sitekey: {sitekey}")
        
        # Создаем event loop для асинхронного решения
        loop = asyncio.get_event_loop()
        
        async def solve_async():
            from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
            from anticaptchaofficial.recaptchav3proxyless import recaptchaV3Proxyless
            
            if version == 'v3':
                solver = recaptchaV3Proxyless()
            else:
                solver = recaptchaV2Proxyless()
                
            solver.set_verbose(1)
            solver.set_key(ANTICAPTCHA_KEY)
            solver.set_website_url(page_url)
            solver.set_website_key(sitekey)
            
            if version == 'v3':
                solver.set_page_action("verify")
                solver.set_min_score(0.3)  # Минимальный допустимый score
            
            # Создаем задачу и ожидаем её завершения
            future = loop.run_in_executor(
                None, 
                solver.solve_and_return_solution if version != 'v3' else solver.solve_and_return_solution
            )
            
            # Ждем решения с таймаутом
            try:
                token = await asyncio.wait_for(future, timeout=self.captcha_timeout)
                if token and not token.startswith('ERROR'):
                    logger.info("AntiCaptcha успешно решил CAPTCHA")
                    return token
                else:
                    logger.error(f"AntiCaptcha вернул ошибку: {token}")
                    return None
            except asyncio.TimeoutError:
                logger.error(f"Таймаут AntiCaptcha ({self.captcha_timeout}s)")
                return None
        
        return await solve_async()
    
    async def _solve_with_twocaptcha(self, page_url: str, sitekey: str, version: str) -> Optional[str]:
        """
        Решает reCAPTCHA с помощью 2Captcha.
        
        Args:
            page_url: URL страницы
            sitekey: Ключ сайта reCAPTCHA
            version: Версия reCAPTCHA
            
        Returns:
            Optional[str]: Токен решения или None
        """
        if not TWOCAPTCHA_AVAILABLE:
            return None
        
        logger.info(f"Решение reCAPTCHA через 2Captcha: {page_url}, sitekey: {sitekey}")
        
        # Создаем event loop для асинхронного решения
        loop = asyncio.get_event_loop()
        
        async def solve_async():
            from twocaptcha import TwoCaptcha
            
            solver = TwoCaptcha(TWOCAPTCHA_KEY)
            
            try:
                # Параметры задачи
                params = {
                    'googlekey': sitekey,
                    'pageurl': page_url,
                    'invisible': 1 if version in ['v3', 'invisible'] else 0
                }
                
                if version == 'v3':
                    params['version'] = 'v3'
                    params['action'] = 'verify'
                    params['score'] = 0.3
                
                # Создаем задачу и ожидаем её завершения
                future = loop.run_in_executor(
                    None, 
                    lambda: solver.recaptcha(**params)
                )
                
                # Ждем решения с таймаутом
                try:
                    result = await asyncio.wait_for(future, timeout=self.captcha_timeout)
                    if result and 'code' in result:
                        logger.info("2Captcha успешно решил CAPTCHA")
                        return result['code']
                    else:
                        logger.error(f"2Captcha вернул неожиданный результат: {result}")
                        return None
                except asyncio.TimeoutError:
                    logger.error(f"Таймаут 2Captcha ({self.captcha_timeout}s)")
                    return None
                
            except Exception as e:
                logger.error(f"Ошибка 2Captcha: {e}")
                return None
        
        return await solve_async()
    
    async def apply_captcha_solution(self, page: Page, token: str, captcha_info: Dict[str, Any]) -> bool:
        """
        Применяет решение CAPTCHA на странице.
        
        Args:
            page: Объект страницы Playwright
            token: Токен решения CAPTCHA
            captcha_info: Информация о CAPTCHA
            
        Returns:
            bool: True если решение успешно применено
        """
        if not token:
            logger.error("Нет токена решения CAPTCHA для применения")
            return False
        
        version = captcha_info.get('version', 'v2')
        
        try:
            if version == 'v3':
                # Для v3 просто вставляем токен через JavaScript
                script = f"""
                (function() {{
                    window.grecaptchaCallback = function(token) {{
                        console.log('reCAPTCHA callback with token:', token);
                    }};
                    
                    if (typeof window.grecaptcha !== 'undefined' && 
                        typeof window.grecaptcha.execute === 'function') {{
                        
                        // Если функция execute уже существует
                        const originalExecute = window.grecaptcha.execute;
                        window.grecaptcha.execute = function(...args) {{
                            console.log('reCAPTCHA execute intercepted');
                            window.grecaptchaCallback('{token}');
                            return Promise.resolve('{token}');
                        }};
                    }} else {{
                        // Если grecaptcha еще не загружен, создаем заглушку
                        window.grecaptcha = {{
                            ready: function(callback) {{ callback(); }},
                            execute: function() {{ 
                                console.log('reCAPTCHA execute stub called');
                                window.grecaptchaCallback('{token}');
                                return Promise.resolve('{token}');
                            }}
                        }};
                    }}
                    
                    // Определяем g-recaptcha-response, который многие формы ищут
                    if (document.querySelector('.g-recaptcha-response')) {{
                        document.querySelector('.g-recaptcha-response').innerHTML = '{token}';
                    }} else {{
                        const input = document.createElement('textarea');
                        input.classList.add('g-recaptcha-response');
                        input.value = '{token}';
                        input.style.display = 'none';
                        document.body.appendChild(input);
                    }}
                    
                    return true;
                }})();
                """
                success = await page.evaluate(script)
                logger.info(f"Применение токена reCAPTCHA v3: {success}")
                return True
            else:
                # Для v2 ищем поле ввода токена
                script = f"""
                (function() {{
                    const textarea = document.querySelector('.g-recaptcha-response');
                    if (textarea) {{
                        textarea.innerHTML = '{token}';
                        return true;
                    }}
                    
                    // Если текстовое поле не найдено, создаем его
                    const input = document.createElement('textarea');
                    input.classList.add('g-recaptcha-response');
                    input.value = '{token}';
                    input.style.display = 'none';
                    document.body.appendChild(input);
                    
                    // Также запускаем callback, если он определен
                    if (typeof ___grecaptcha_cfg !== 'undefined') {{
                        // Пытаемся найти callback функцию в конфигурации
                        for (const key in ___grecaptcha_cfg.clients) {{
                            if (___grecaptcha_cfg.clients[key].hasOwnProperty('callback')) {{
                                ___grecaptcha_cfg.clients[key]['callback']('{token}');
                                return true;
                            }}
                        }}
                    }}
                    
                    return true;
                }})();
                """
                success = await page.evaluate(script)
                logger.info(f"Применение токена reCAPTCHA v2: {success}")
                
                # Пытаемся найти и нажать кнопку отправки формы
                submit_button = await page.query_selector('button[type="submit"], input[type="submit"], .g-recaptcha + button')
                if submit_button:
                    await submit_button.click()
                    logger.info("Кнопка отправки формы нажата")
                
                return True
        except Exception as e:
            logger.error(f"Ошибка при применении решения CAPTCHA: {e}")
            return False
    
    async def handle_captcha(self, page: Page) -> bool:
        """
        Обрабатывает CAPTCHA на странице - определяет, решает и применяет решение.
        
        Args:
            page: Объект страницы Playwright
            
        Returns:
            bool: True если CAPTCHA успешно обработана
        """
        # Обнаруживаем CAPTCHA
        captcha_info = await self.detect_captcha(page)
        if not captcha_info:
            logger.debug("CAPTCHA не обнаружена, продолжаем работу")
            return True
        
        logger.info(f"Обнаружена CAPTCHA типа {captcha_info.get('type')} версии {captcha_info.get('version', 'unknown')}")
        
        # Если это reCAPTCHA, пытаемся решить
        if captcha_info.get('type') == 'recaptcha':
            # Получаем решение
            token = await self.solve_recaptcha(page, captcha_info)
            if not token:
                logger.error("Не удалось получить токен решения CAPTCHA")
                return False
            
            # Применяем решение
            success = await self.apply_captcha_solution(page, token, captcha_info)
            if not success:
                logger.error("Не удалось применить решение CAPTCHA")
                return False
            
            # Ждем перезагрузки страницы или изменения URL
            current_url = page.url
            try:
                await page.wait_for_function(
                    'document.querySelector(".g-recaptcha") === null || window.location.href !== arguments[0]',
                    args=[current_url],
                    timeout=10000
                )
                logger.info("CAPTCHA решена успешно, страница обновлена")
                return True
            except Exception:
                # Проверяем, исчезла ли CAPTCHA
                if not await page.query_selector('.g-recaptcha, iframe[src*="recaptcha"]'):
                    logger.info("CAPTCHA решена успешно")
                    return True
                logger.warning("После применения решения CAPTCHA страница не обновилась")
                return True  # Возвращаем True, так как мы применили решение
        
        # Для Cloudflare или других типов CAPTCHA
        logger.warning(f"Обработка CAPTCHA типа {captcha_info.get('type')} не реализована")
        return False

# Функция-помощник для быстрого создания решателя CAPTCHA
def get_captcha_solver(use_anticaptcha: bool = True, use_twocaptcha: bool = True) -> CaptchaSolver:
    """
    Создает и возвращает настроенный экземпляр CaptchaSolver.
    
    Args:
        use_anticaptcha: Использовать AntiCaptcha (если доступно)
        use_twocaptcha: Использовать 2Captcha (если доступно)
        
    Returns:
        CaptchaSolver: Экземпляр решателя CAPTCHA
    """
    # Проверяем наличие API ключей в переменных окружения
    if use_anticaptcha and not ANTICAPTCHA_KEY:
        logger.warning("AntiCaptcha API ключ не найден в переменных окружения (ANTICAPTCHA_KEY)")
    
    if use_twocaptcha and not TWOCAPTCHA_KEY:
        logger.warning("2Captcha API ключ не найден в переменных окружения (TWOCAPTCHA_KEY)")
    
    return CaptchaSolver(use_anticaptcha=use_anticaptcha, use_twocaptcha=use_twocaptcha)

# Пример использования
if __name__ == "__main__":
    # Настраиваем логирование
    logging.basicConfig(level=logging.INFO)
    
    print("Этот модуль предназначен для импорта в другие скрипты.")
    print("Для использования импортируйте get_captcha_solver из recaptcha_solver.py")
    print("\nПример использования:")
    print("from recaptcha_solver import get_captcha_solver")
    print("\nasync def main():")
    print("    solver = get_captcha_solver()")
    print("    ... создание страницы Playwright ...")
    print("    await solver.handle_captcha(page)")