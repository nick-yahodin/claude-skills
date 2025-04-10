#!/usr/bin/env python3
"""
Парсер для сайта Gallito Уругвай (недвижимость - terrenos/venta).
"""

import logging
import re
import asyncio
import random
from typing import List, Optional, Dict, Any, Tuple

from playwright.async_api import Page, ElementHandle
from pydantic import HttpUrl

# Импорты относительно папки UruguayLands/app
from .base import BaseParser # Относительный импорт базового класса
from app.models import Listing # Абсолютный импорт модели из app

# Вспомогательная функция для проверки "N/A"
def _is_na(value: Optional[str]) -> bool:
    """Проверяет, является ли строка None, пустой или содержит 'N/A'."""
    return not value or value.strip().lower() in ["n/a", "na", ""]

class GallitoParser(BaseParser):
    """
    Парсер для Gallito.com.uy (Двухэтапный)
    Этап 1: Извлечение URL со страницы списка.
    Этап 2: Переход на страницу деталей и извлечение полной информации.
    """
    SOURCE_NAME = "gallito"
    BASE_URL = "https://www.gallito.com.uy"
    SEARCH_URL_TEMPLATE = BASE_URL + "/inmuebles/campos-y-chacras/venta?pag={page}"

    def __init__(self, proxy_list: Optional[List[str]] = None):
        super().__init__(proxy_list=proxy_list)
        # Увеличиваем задержку для обхода Cloudflare
        self.request_delay = (5, 15)  # Увеличенная задержка между запросами
        # Селекторы для СТРАНИЦЫ СПИСКА (только для поиска ссылок)
        self.listing_link_selector = 'a[href*="-inmuebles-"]'
        self.blacklist_keywords = [
            'alquiler', 'arriendo', 'temporal',
            'permuta', 'vehiculo', 'auto', 'moto', 'maquinaria'
        ]
        self.list_selectors = {
            "item": "article.aviso-container",
            # ... остальные селекторы ...
        }
        self.detail_selectors = {
            "price": ".precio strong", # Проверить
            # ... остальные селекторы ...
        }
        
        # Флаг для обнаружения блокировки
        self.cloudflare_detected = False

    async def _get_page_url(self, page_number: int) -> str:
        """Возвращает URL для конкретной страницы результатов Gallito."""
        if page_number == 1:
            return f"{self.BASE_URL}?pag=1"
        else:
            return f"{self.BASE_URL}/pagina{page_number}?pag={page_number}"

    async def _bypass_cloudflare(self, page: Page) -> bool:
        """
        Метод для обхода Cloudflare.
        Выполняет действия для эмуляции человеческого поведения.
        
        Returns:
            bool: True если обход удался, False если нет
        """
        self.logger.info("Пытаемся обойти Cloudflare защиту...")
        
        try:
            # Проверяем наличие Cloudflare challenge
            cloudflare_selectors = [
                '#challenge-running', 
                '.cf-browser-verification', 
                '#cf-challenge-running',
                'div[data-translate="checking_browser"]'
            ]
            
            for selector in cloudflare_selectors:
                has_element = await page.query_selector(selector)
                if has_element:
                    self.logger.warning(f"Обнаружен Cloudflare challenge: {selector}")
                    self.cloudflare_detected = True
                    break
            
            if not self.cloudflare_detected:
                # Проверка на наличие CAPTCHA
                captcha_selectors = [
                    '.g-recaptcha', 
                    '#recaptcha', 
                    'iframe[src*="recaptcha"]',
                    'iframe[src*="captcha"]'
                ]
                
                for selector in captcha_selectors:
                    has_captcha = await page.query_selector(selector)
                    if has_captcha:
                        self.logger.warning(f"Обнаружена CAPTCHA: {selector}")
                        self.cloudflare_detected = True
                        break
            
            if not self.cloudflare_detected:
                self.logger.info("Cloudflare или CAPTCHA не обнаружены, продолжаем.")
                return True
                
            # Если обнаружен Cloudflare - пытаемся обойти
            self.logger.info("Ожидание загрузки страницы Cloudflare (20 сек)...")
            await asyncio.sleep(20)  # Даем время для загрузки JavaScript
            
            # Эмуляция человеческого поведения
            await self._simulate_human_behavior(page)
            
            # Проверяем, удалось ли пройти защиту
            for selector in cloudflare_selectors + captcha_selectors:
                still_has_element = await page.query_selector(selector)
                if still_has_element:
                    self.logger.error(f"Cloudflare/CAPTCHA все еще активен: {selector}")
                    return False
                    
            self.logger.info("Cloudflare/CAPTCHA обход кажется успешным!")
            return True
                
        except Exception as e:
            self.logger.error(f"Ошибка при попытке обойти Cloudflare: {e}")
            return False
    
    async def _simulate_human_behavior(self, page: Page):
        """Эмулирует действия человека на странице для обхода защиты."""
        self.logger.info("Эмуляция человеческого поведения...")
        
        # Случайные перемещения мыши
        for _ in range(5):
            x = random.randint(100, 700)
            y = random.randint(100, 500)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.5, 2.0))
        
        # Прокрутка страницы
        await page.mouse.wheel(delta_y=random.randint(300, 700))
        await asyncio.sleep(random.uniform(1.0, 3.0))
        
        # Еще прокрутка
        await page.mouse.wheel(delta_y=random.randint(-200, -500))
        await asyncio.sleep(random.uniform(1.0, 2.0))
        
        # Нажатие клавиш
        await page.keyboard.press("Tab")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await page.keyboard.press("Tab")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        self.logger.info("Человеческое поведение эмулировано.")
    
    async def _navigate_and_handle_cloudflare(self, page: Page, url: str) -> bool:
        """
        Переходит по URL и обрабатывает Cloudflare/CAPTCHA если обнаружены.
        
        Returns:
            bool: True если страница успешно загружена, False в случае ошибки
        """
        self.logger.info(f"Переход на URL с обработкой Cloudflare: {url}")
        
        try:
            # Устанавливаем дополнительные заголовки
            await page.set_extra_http_headers({
                'Accept-Language': 'es-UY,es;q=0.9,en;q=0.8',
                'Sec-Ch-Ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0'
            })
            
            # Переход на URL с увеличенным таймаутом
            await page.goto(url, wait_until='domcontentloaded', timeout=90000)
            await asyncio.sleep(random.uniform(3, 7))  # Дополнительная пауза после загрузки
            
            # Проверяем и обходим Cloudflare если нужно
            bypass_success = await self._bypass_cloudflare(page)
            if not bypass_success:
                self.logger.warning(f"Не удалось обойти Cloudflare для {url}")
                return False
                
            # Дополнительно ждем загрузки контента
            await page.wait_for_load_state('networkidle', timeout=15000)
            
            # Делаем скриншот для отладки
            screenshot_path = f"gallito_success_{random.randint(1000, 9999)}.png"
            await page.screenshot(path=screenshot_path)
            self.logger.info(f"Сделан скриншот после загрузки: {screenshot_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при переходе на {url} с обработкой Cloudflare: {e}")
            return False
    
    async def run(self, max_pages: Optional[int] = None, headless: bool = True, detail_processing: bool = False) -> List[Listing]:
        """
        Переопределяем метод run с учетом обхода Cloudflare.
        """
        self.logger.info(f"Запуск парсера Gallito с обходом Cloudflare (headless={headless})...")
        
        # Запускаем парсер в режиме полного браузера для обхода Cloudflare
        if headless:
            self.logger.warning("Для обхода Cloudflare рекомендуется режим без headless. Переключаемся.")
            headless = False
            
        # Вызываем родительский метод run с обновленными параметрами
        return await super().run(max_pages=max_pages, headless=headless, detail_processing=detail_processing)
    
    async def _extract_listings_from_page(self, page: Page) -> List[Listing]:
        """
        Извлекает данные объявлений со страницы.
        Шаг 1: Извлекает URL объявлений со страницы списка.
        Шаг 2: Переходит на каждую страницу объявления и извлекает полные данные.
        """
        # Проверяем, нужно ли обойти Cloudflare
        if not await self._navigate_and_handle_cloudflare(page, page.url):
            self.logger.error("Не удалось обойти Cloudflare защиту. Прерываем парсинг страницы.")
            return []
            
        # Оригинальный код извлечения объявлений
        listing_urls: List[str] = []
        link_selector = self.listing_link_selector
        self.logger.debug(f"Ищем ссылки по селектору: {link_selector}")
        link_elements = await page.query_selector_all(link_selector)
        self.logger.info(f"Найдено {len(link_elements)} потенциальных ссылок на странице списка.")

        processed_urls_on_page = set()

        for link_el in link_elements:
            url = await link_el.get_attribute('href')
            if not url: continue

            if url.startswith('//'): url = f"https:{url}"
            elif url.startswith('/'): url = f"https://www.gallito.com.uy{url}"
            clean_url = url.split('?')[0].split('#')[0]

            if "-inmuebles-" in clean_url and clean_url not in processed_urls_on_page:
                if clean_url not in self.global_seen_urls:
                    listing_urls.append(clean_url)
                    processed_urls_on_page.add(clean_url)
                else:
                    self.logger.debug(f"URL {clean_url} уже обработан глобально.")
            elif url in processed_urls_on_page:
                 self.logger.debug(f"Обнаружен дубликат URL на странице списка: {clean_url}. Пропуск.")

        self.logger.info(f"Извлечено {len(listing_urls)} новых уникальных URL со страницы {self.stats['pages_processed'] + 1}.")

        listings_data: List[Dict[str, Any]] = []
        for detail_url in listing_urls:
            try:
                listing_data_dict = await self._extract_data_from_detail_page(page, detail_url)
                if listing_data_dict:
                    if str(listing_data_dict['url']) not in self.global_seen_urls:
                        listings_data.append(listing_data_dict)
                        self.global_seen_urls.add(str(listing_data_dict['url']))
                    else:
                         self.logger.debug(f"Объявление с URL {listing_data_dict['url']} уже было обработано ранее. Пропуск.")
                else:
                    self.logger.debug(f"Не удалось извлечь данные или объявление отфильтровано: {detail_url}")
            except Exception as e:
                self.logger.error(f"Ошибка при обработке страницы объявления {detail_url}: {e}", exc_info=True)
                self.stats['errors'] += 1
            finally:
                 await self._delay()

        final_listings: List[Listing] = []
        for data_dict in listings_data:
            try:
                listing_obj = Listing(**data_dict)
                title_lower = listing_obj.title.lower()
                if any(keyword in title_lower for keyword in self.blacklist_keywords):
                     self.logger.debug(f"Пропуск по blacklist (после парсинга): {listing_obj.title}")
                     continue
                final_listings.append(listing_obj)
            except Exception as e:
                 self.logger.warning(f"Ошибка валидации Pydantic для {data_dict.get('url', 'N/A')}: {e}")
                 self.stats['errors'] += 1
                 
        self.logger.info(f"Успешно создано {len(final_listings)} объектов Listing после валидации.")
        return final_listings

    async def _extract_data_from_detail_page(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        """Извлекает данные со страницы деталей объявления Gallito."""
        self.logger.info(f"Извлечение данных со страницы деталей: {url}")
        data: Dict[str, Any] = {"source": self.SOURCE_NAME, "url": url}

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=45000)
            await self._delay()
        except Exception as e:
            self.logger.error(f"Не удалось перейти на страницу деталей {url}: {e}")
            return None

        try:
             await page.wait_for_selector('#div_datosBasicos h1.titulo', state='visible', timeout=30000)
        except Exception:
             self.logger.warning(f"Не удалось дождаться заголовка на {url}, возможно, страница изменилась или невалидна.")
             return None

        # --- Изображение (из мета-тега) ---
        data['image_url'] = None
        meta_img_el = await page.query_selector('meta[property="og:image"]')
        if meta_img_el:
            img_src = await meta_img_el.get_attribute('content')
            if img_src:
                try:
                    if isinstance(img_src, str) and img_src.startswith(('http://', 'https://')):
                        data['image_url'] = HttpUrl(img_src)
                        self.logger.debug(f"Изображение найдено в мета-теге: {img_src}")
                    else:
                        self.logger.debug(f"Невалидный формат URL изображения из мета-тега: {img_src}")
                except Exception as e:
                    self.logger.debug(f"Ошибка валидации URL изображения из мета-тега: {img_src} для {url}. Ошибка: {e}")

        # --- Заголовок ---
        title_el = await page.query_selector('#div_datosBasicos h1.titulo')
        data['title'] = (await title_el.inner_text()).strip() if title_el else "N/A"
        if _is_na(data['title']):
            meta_title_el = await page.query_selector('meta[property="og:title"]')
            if meta_title_el:
                meta_title = await meta_title_el.get_attribute('content')
                if meta_title:
                    data['title'] = meta_title.strip()
                    self.logger.debug(f"Заголовок извлечен из meta[og:title] (fallback) для {url}")

        # --- Цена ---
        price_el = await page.query_selector('#div_datosBasicos span.precio')
        data['price'] = (await price_el.inner_text()).strip() if price_el else "N/A"

        # --- Описание (текст) --- 
        description_text = "N/A"
        desc_elements = await page.query_selector_all('section#descripcion div.p-3 p') 
        if desc_elements:
            desc_parts = [(await p.inner_text()).strip() for p in desc_elements]
            description_text = "\n".join(filter(None, desc_parts))
        else:
             desc_container = await page.query_selector('section#descripcion div.p-3')
             if desc_container:
                  description_text = (await desc_container.inner_text()).strip()
        data['description'] = description_text
        if _is_na(data['description']):
            meta_desc_el = await page.query_selector('meta[property="og:description"]')
            if meta_desc_el:
                meta_desc = await meta_desc_el.get_attribute('content')
                if meta_desc:
                    data['description'] = meta_desc.strip()
                    self.logger.debug(f"Описание извлечено из meta[og:description] (fallback) для {url}")
            if _is_na(data['description']):
                 meta_desc_name_el = await page.query_selector('meta[name="description"]')
                 if meta_desc_name_el:
                     meta_desc_name = await meta_desc_name_el.get_attribute('content')
                     if meta_desc_name:
                         data['description'] = meta_desc_name.strip()
                         self.logger.debug(f"Описание извлечено из meta[name=description] (fallback) для {url}")

        # --- Локация --- 
        departments = [
            'montevideo', 'canelones', 'maldonado', 'rocha', 'colonia', 'san jose', 'soriano',
            'rio negro', 'paysandu', 'salto', 'artigas', 'rivera', 'tacuarembo', 'durazno',
            'flores', 'florida', 'lavalleja', 'treinta y tres', 'cerro largo'
        ]
        data['location'] = "N/A"
        found_specific_location = False
        location_data_el = await page.query_selector('#div_datosOperacion .wrapperDatos:has(i.fa-map-marked) p')
        if location_data_el:
            specific_location = (await location_data_el.inner_text()).strip()
            if not _is_na(specific_location):
                 data['location'] = specific_location
                 found_specific_location = True
                 self.logger.debug(f"Локация найдена в блоке данных: {specific_location}")
        if not found_specific_location:
            breadcrumb_el = await page.query_selector('ol#ol_breadcrumb li:last-child a')
            if breadcrumb_el:
                specific_location = (await breadcrumb_el.inner_text()).strip()
                if specific_location and specific_location.lower() not in ['terrenos', 'venta', 'inmuebles'] and len(specific_location) > 2:
                    data['location'] = specific_location
                    found_specific_location = True
                    self.logger.debug(f"Локация найдена в хлебных крошках: {specific_location}")
        if not found_specific_location:
            desc_lower = description_text.lower() if not _is_na(description_text) else ""
            title_lower = data['title'].lower() if not _is_na(data['title']) else ""
            found_dept_in_text = None
            for dept in departments:
                if dept in desc_lower or dept in title_lower:
                    found_dept_in_text = dept.title()
                    data['location'] = found_dept_in_text
                    self.logger.debug(f"Департамент найден в тексте: {found_dept_in_text}")
                    break
        if _is_na(data['location']):
            meta_dept_el = await page.query_selector('meta[name="cXenseParse:recs:deaprtamento"]')
            meta_barrio_el = await page.query_selector('meta[name="cXenseParse:recs:barrio"]')
            meta_dept = (await meta_dept_el.get_attribute('content')).strip().title() if meta_dept_el else None
            meta_barrio = (await meta_barrio_el.get_attribute('content')).strip().title() if meta_barrio_el else None
            location_parts = []
            if meta_barrio and not _is_na(meta_barrio):
                location_parts.append(meta_barrio)
            if meta_dept and not _is_na(meta_dept):
                if not meta_barrio or meta_barrio.lower() != meta_dept.lower():
                    location_parts.append(meta_dept)
            if location_parts:
                data['location'] = ", ".join(location_parts)
                self.logger.debug(f"Локация извлечена из cXense meta-тегов (fallback): {data['location']} для {url}")
            elif not _is_na(data['title']):
                 data['location'] = data['title'] 
                 self.logger.debug(f"Локация не найдена, используется fallback (title): {data['location']}")

        # --- Площадь --- 
        data['area'] = "N/A"
        found_area_in_data = False
        area_data_el = await page.query_selector('#div_datosOperacion .wrapperDatos:has(i.fa-square) p')
        if area_data_el:
            area_text = (await area_data_el.inner_text()).strip()
            match = re.search(r'(\d+[.,]?\d*)\s*(Mts|m2|m²)', area_text, re.IGNORECASE)
            if match:
                 value_str = match.group(1).replace('.', '').replace(',', '.')
                 try:
                     value = float(value_str)
                     data['area'] = f"{value:,.0f} m²".replace(",", ".")
                     found_area_in_data = True
                     self.logger.debug(f"Площадь найдена в блоке данных: {data['area']}")
                 except ValueError:
                     self.logger.debug(f"Не удалось преобразовать площадь из блока данных: {area_text}")
        if not found_area_in_data and not _is_na(description_text):
            pattern = r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+)\s*(m2|m²|mts|metros?|ha|hectareas?|hectáreas)'
            matches = re.finditer(pattern, description_text, re.IGNORECASE)
            area_m2 = None
            area_ha = None
            for match in matches:
                value_str = match.group(1).replace('.', '').replace(',', '.')
                unit = match.group(2).lower()
                try:
                    value = float(value_str)
                    if unit.startswith('h'): area_ha = value
                    elif unit.startswith('m'): area_m2 = value
                except ValueError:
                    self.logger.debug(f"Не удалось преобразовать площадь из описания '{value_str}'.")
            if area_ha is not None:
                data['area'] = f"{area_ha:,.2f} ha".replace(",", "X").replace(".", ",").replace("X", ".")
                self.logger.debug(f"Площадь (га) найдена в описании: {data['area']}")
            elif area_m2 is not None:
                data['area'] = f"{area_m2:,.0f} m²".replace(",", ".")
                self.logger.debug(f"Площадь (м²) найдена в описании: {data['area']}")
        if _is_na(data['area']):
             self.logger.debug(f"Площадь не найдена.")
       
        # --- Характеристики / Utilities ---
        data['utilities'] = []
        utilities_elements = await page.query_selector_all('section#caracteristicas ul#ul_caracteristicas li')
        if utilities_elements:
            for li in utilities_elements:
                utility_text = (await li.inner_text()).strip()
                if utility_text:
                    if ':' in utility_text:
                        utility_text = utility_text.split(':', 1)[-1].strip()
                    if not _is_na(utility_text):
                        data['utilities'].append(utility_text)
            if data['utilities']:
                self.logger.debug(f"Найдены характеристики: {data['utilities']}")
        else:
             self.logger.debug("Секция характеристик не найдена или пуста.")
        
        final_data = {
            'url': url,
            'source': 'gallito',
            'title': data.get('title', 'N/A'),
            'price': data.get('price', 'N/A'),
            'description': data.get('description', 'N/A'),
            'location': data.get('location', 'N/A'),
            'area': data.get('area', 'N/A'),
            'image_url': data.get('image_url'),
            'utilities': ", ".join(data.get('utilities', [])) if data.get('utilities') else "Не указано"
        }
        
        if all(_is_na(v) for k, v in final_data.items() if k not in ['url', 'source', 'image_url', 'utilities']):
            self.logger.warning(f"Почти все поля N/A для {url}. Возможно, ошибка парсинга.")
            
        self.logger.info(f"Успешно извлечены данные для {url}: Area='{final_data['area']}', Location='{final_data['location']}'")
        return final_data 