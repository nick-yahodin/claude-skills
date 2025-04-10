#!/usr/bin/env python3
"""
Парсер для сайта InfoCasas Уругвай (недвижимость - terrenos/venta).
Двухэтапный: сначала URL со списка, затем парсинг страницы объявления.
"""

import logging
import re
import asyncio
import random
from typing import List, Optional, Dict, Any

from playwright.async_api import Page, ElementHandle
from pydantic import HttpUrl

# Импорты относительно папки UruguayLands/app
from .base import BaseParser # Относительный импорт
from app.models import Listing # Абсолютный импорт

class InfoCasasParser(BaseParser):
    """
    Парсер для InfoCasas.com.uy
    Реализует специфическую логику для сайта InfoCasas.
    """
    SOURCE_NAME = "infocasas"
    BASE_URL = "https://www.infocasas.com.uy"
    SEARCH_URL_TEMPLATE = BASE_URL + "/venta/campos/campo/pagina{page}"

    def __init__(self, proxy_list: Optional[List[str]] = None):
        super().__init__(proxy_list=proxy_list)
        self.request_delay = (3, 8)  # Увеличиваем задержку для более стабильной работы
        # Селекторы для СТРАНИЦЫ СПИСКА
        self.list_selectors = {
            'card_container': 'div.listingCard', # <-- НОВЫЙ СЕЛЕКТОР ПО СКРИНШОТУ
            'url': 'a.lc-cardCover', # <-- Основной селектор URL по скриншоту
        }
        # Селекторы для СТРАНИЦЫ ДЕТАЛЕЙ ОБЪЯВЛЕНИЯ (могут потребовать уточнения)
        self.listing_selectors = {
            'title': 'h1.main-title',
            'price': 'strong[data-qa="adPagePrice"]',
            'location': 'div.title-container a[data-qa="overviewNeighborhoodLink"]',
            'features_list': 'ul.property-main-features', # Список характеристик
            'feature_item': 'li.item-feature', # Элемент характеристики
            'image_gallery': 'div[data-qa="gallery"]', # Галерея для поиска первого фото
            'image': 'img', # Изображение внутри галереи
            'description_content': 'div#descriptionContent',
            'amenities_section': 'div#section-amenities', # Секция удобств
            'amenity_item': 'li.item-feature', # Элемент удобства (может совпадать с feature_item)
        }
        self.blacklist_keywords = [
            'alquiler', 'arriendo', 'temporal',
            'permuta', 'vehiculo', 'auto', 'moto', 'maquinaria'
        ]
        # Пока не используем whitelist для InfoCasas
        # self.whitelist_keywords = [...] 
        
        # Добавляем флаг для логики повторных попыток
        self.current_retry = 0
        self.max_retry_attempts = 3

    async def _get_page_url(self, page_number: int) -> str:
        """Возвращает URL для конкретной страницы результатов InfoCasas.
           Убрали сортировку по дате для стабильности.
        """
        if page_number == 1:
            # Убираем параметр сортировки
            return self.BASE_URL
        else:
            # Убираем параметр сортировки
            return f"{self.BASE_URL}/pagina{page_number}"

    async def run(self, max_pages: Optional[int] = None, headless: bool = True, detail_processing: bool = False) -> List[Listing]:
        """
        Переопределяем метод run с дополнительной логикой обработки ошибок.
        """
        self.logger.info(f"Запуск парсера InfoCasas с улучшенной обработкой ошибок (headless={headless})...")
        
        try:
            # Запускаем с небольшим таймаутом перед началом
            await asyncio.sleep(2)
            
            # Вызываем родительский метод run
            result = await super().run(max_pages=max_pages, headless=headless, detail_processing=detail_processing)
            
            # Дополнительная проверка результатов
            if not result:
                self.logger.warning("Парсер вернул пустой список объявлений. Проверка завершена успешно, но данных нет.")
            else:
                self.logger.info(f"Парсер успешно завершен. Найдено объявлений: {len(result)}")
                
            return result
                
        except Exception as e:
            self.logger.error(f"Критическая ошибка в InfoCasasParser.run: {e}", exc_info=True)
            # Возвращаем пустой список в случае ошибки, чтобы приложение продолжало работу
            return []

    async def _scroll_and_load(self, page: Page, scrolls: int = 5, delay: float = 3.0):
        """Прокручивает страницу вниз для загрузки динамического контента. Увеличены параметры."""
        self.logger.debug(f"Начинаю прокрутку страницы ({scrolls} раз с задержкой {delay} сек)...")
        
        try:
            # Получаем высоту страницы
            page_height = await page.evaluate('document.body.scrollHeight')
            
            # Прокручиваем с более плавным шагом
            viewport_height = await page.evaluate('window.innerHeight')
            scroll_step = viewport_height // 2  # Половина высоты окна
            
            for i in range(scrolls):
                # Прокручиваем с указанным шагом вместо полной высоты окна
                scroll_position = scroll_step * (i + 1)
                await page.evaluate(f'window.scrollTo(0, {scroll_position})')
                self.logger.debug(f"Прокрутка {i+1}/{scrolls} до позиции {scroll_position}px")
                
                # Добавляем небольшое движение мыши для естественности
                x = random.randint(100, 700)
                y = random.randint(100, 500)
                await page.mouse.move(x, y)
                
                await asyncio.sleep(delay)
                
            # Финальная прокрутка в самый низ
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(delay)
            
            # И немного вверх для естественности
            await page.evaluate(f'window.scrollTo(0, document.body.scrollHeight - {viewport_height})')
            
            self.logger.debug("Прокрутка завершена.")
            
        except Exception as e:
            self.logger.warning(f"Ошибка при прокрутке страницы: {e}. Продолжаем работу.")
        
    async def _extract_listings_from_page(self, page: Page) -> List[Listing]:
        """
        Извлекает URL объявлений со страницы списка, переходит на каждую
        страницу деталей и собирает полные данные.
        """
        
        # --- Шаг 0: Ожидание полной загрузки страницы ---
        try:
            # Сначала ждем загрузки DOM
            self.logger.debug("Ожидание загрузки DOM (до 30 сек)...")
            await page.wait_for_load_state('domcontentloaded', timeout=30000)
            
            # Затем ждем загрузки сетевых ресурсов с увеличенным таймаутом
            self.logger.debug("Ожидание networkidle (до 60 сек)...")
            await page.wait_for_load_state('networkidle', timeout=60000)
            self.logger.debug("Состояние networkidle достигнуто.")
            
            # Сделаем скриншот для отладки
            screenshot_path = f"infocasas_page_{self.stats['pages_processed'] + 1}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            self.logger.info(f"Сделан скриншот страницы: {screenshot_path}")
            
        except Exception as e:
             self.logger.warning(f"Таймаут ожидания загрузки страницы: {e}. Попытка продолжить...")
             
        # --- Шаг 1: Более агрессивная прокрутка и ожидание ---
        await self._scroll_and_load(page, scrolls=7, delay=3.0)  # Увеличиваем прокрутку
        
        # Дополнительное ожидание после прокрутки
        await asyncio.sleep(5)
        
        # --- Шаг 2: Более гибкое извлечение URL со страницы списка ---
        listing_urls: List[str] = []
        
        # Пробуем несколько селекторов для карточек
        card_selectors = [
            self.list_selectors['card_container'],  # Основной селектор
            'div.sc-item',                         # Альтернативный селектор 1
            'div.property-list-item',              # Альтернативный селектор 2
            'article.property-card'                # Альтернативный селектор 3
        ]
        
        # Пробуем несколько селекторов для ссылок
        url_selectors = [
            self.list_selectors['url'],  # Основной селектор
            'a.property-link',          # Альтернативный селектор 1
            'a[href*="/inmueble/"]',    # Альтернативный селектор 2
            'a.card-link'               # Альтернативный селектор 3
        ]
        
        # Попробуем найти карточки объявлений по разным селекторам
        cards = []
        used_card_selector = None
        
        for selector in card_selectors:
            self.logger.debug(f"Пробуем найти карточки по селектору: {selector}")
            cards = await page.query_selector_all(selector)
            if cards and len(cards) > 0:
                self.logger.info(f"Найдено {len(cards)} карточек по селектору: {selector}")
                used_card_selector = selector
                break
        
        if not cards:
            # Если не нашли карточки по селекторам - пробуем найти прямо ссылки
            self.logger.warning("Не удалось найти карточки по селекторам. Пробуем искать прямо ссылки.")
            
            for url_selector in url_selectors:
                self.logger.debug(f"Пробуем найти ссылки по селектору: {url_selector}")
                url_elements = await page.query_selector_all(url_selector)
                
                if url_elements and len(url_elements) > 0:
                    self.logger.info(f"Найдено {len(url_elements)} прямых ссылок по селектору: {url_selector}")
                    
                    for url_el in url_elements:
                        url = await url_el.get_attribute('href')
                        if url and (url.startswith('/') or url.startswith('http')):
                            if url.startswith('/'):
                                full_url = f"https://www.infocasas.com.uy{url.split('?')[0]}"
                            else:
                                full_url = url.split('?')[0]
                                
                            if "infocasas.com.uy" in full_url and full_url not in self.global_seen_urls:
                                listing_urls.append(full_url)
                                self.global_seen_urls.add(full_url)
                                
                    if listing_urls:
                        break
        else:
            # Обрабатываем найденные карточки
            self.logger.info(f"Обрабатываем {len(cards)} карточек. Используемый селектор: {used_card_selector}")
            
            processed_urls_on_page = set()
            for card in cards:
                # Пробуем разные селекторы для поиска ссылки внутри карточки
                found_url = False
                
                for url_selector in url_selectors:
                    url_el = await card.query_selector(url_selector)
                    
                    if url_el:
                        url = await url_el.get_attribute('href')
                        if url and (url.startswith('/') or url.startswith('http')):
                            if url.startswith('/'):
                                full_url = f"https://www.infocasas.com.uy{url.split('?')[0]}"
                            else:
                                full_url = url.split('?')[0]
                                
                            if full_url not in processed_urls_on_page and full_url not in self.global_seen_urls:
                                listing_urls.append(full_url)
                                processed_urls_on_page.add(full_url)
                                self.global_seen_urls.add(full_url)
                                found_url = True
                                break
                
                if not found_url:
                    self.logger.debug(f"Не удалось найти URL в карточке по селекторам.")
        
        self.logger.info(f"Извлечено {len(listing_urls)} новых уникальных URL со страницы {self.stats['pages_processed'] + 1}.")
        
        # --- Шаг 3: Более устойчивый парсинг страниц объявлений ---
        listings_data: List[Dict[str, Any]] = []
        for url in listing_urls:
            try:
                self.logger.info(f"Переход на страницу объявления: {url}")
                
                # Увеличиваем таймауты и добавляем повторные попытки
                retry_count = 0
                success = False
                
                while retry_count < 3 and not success:
                    try:
                        # Переход с увеличенным таймаутом
                        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                        
                        # Дополнительное ожидание загрузки сети
                        await page.wait_for_load_state('networkidle', timeout=30000)
                        
                        # Задержка для полной загрузки JS
                        await asyncio.sleep(random.uniform(3, 6))
                        
                        # Считаем загрузку успешной
                        success = True
                    except Exception as nav_err:
                        retry_count += 1
                        self.logger.warning(f"Ошибка при загрузке страницы {url} (попытка {retry_count}/3): {nav_err}")
                        if retry_count < 3:
                            await asyncio.sleep(5 * retry_count)  # Увеличиваем задержку с каждой попыткой
                            
                if not success:
                    self.logger.error(f"Не удалось загрузить страницу {url} после 3 попыток. Пропускаем.")
                    continue
                
                # Скриншот для отладки
                detail_screenshot = f"infocasas_detail_{random.randint(1000, 9999)}.png"
                await page.screenshot(path=detail_screenshot)
                self.logger.debug(f"Сделан скриншот детальной страницы: {detail_screenshot}")

                # Извлечение данных с повышенной отказоустойчивостью
                listing_data = await self._extract_data_from_listing_page(page, url)
                
                if listing_data:
                    # Добавляем в список и в глобальное множество обработанных
                    listings_data.append(listing_data)
                    self.logger.info(f"Успешно извлечены данные для {url}")
                else:
                    self.logger.debug(f"Не удалось извлечь данные для: {url}")

            except Exception as e:
                self.logger.error(f"Ошибка при обработке страницы объявления {url}: {e}", exc_info=True)
                self.stats['errors'] += 1
            finally:
                 await self._delay() # Задержка после парсинга

        # --- Шаг 4: Преобразование в объекты Listing с обработкой ошибок ---
        final_listings: List[Listing] = []
        for data_dict in listings_data:
             try:
                 listing_obj = Listing(**data_dict)
                 final_listings.append(listing_obj)
                 self.logger.debug(f"Создан объект Listing для {data_dict.get('url', 'N/A')}")
             except Exception as e:
                  self.logger.warning(f"Ошибка валидации Pydantic для {data_dict.get('url', 'N/A')}: {e}")
                  # Сохраняем проблемные данные для отладки
                  error_file = f"infocasas_error_data_{random.randint(1000, 9999)}.json"
                  try:
                      import json
                      with open(error_file, 'w') as f:
                          json.dump(data_dict, f, default=str, indent=2)
                      self.logger.info(f"Сохранены проблемные данные: {error_file}")
                  except Exception as json_err:
                      self.logger.error(f"Не удалось сохранить проблемные данные: {json_err}")
                  
        self.logger.info(f"Собрано {len(final_listings)} объявлений после парсинга страниц деталей.")
        return final_listings

    async def _safe_get_text(self, element: Optional[ElementHandle], selector_name: str, url: str) -> str:
        """Безопасно получает текст из элемента."""
        if element:
            try:
                return (await element.inner_text()).strip()
            except Exception as e:
                self.logger.debug(f"Не удалось получить текст для селектора '{selector_name}' на {url}: {e}")
        return ""

    async def _extract_data_from_listing_page(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        """Извлекает данные со страницы конкретного объявления InfoCasas."""
        data: Dict[str, Any] = {"source": self.SOURCE_NAME, "url": url}
        sel = self.listing_selectors

        try:
            # Ожидаем ключевой элемент, например, заголовок
            self.logger.debug(f"Ожидание заголовка '{sel['title']}' на {url}")
            await page.wait_for_selector(sel['title'], timeout=15000)
        except Exception as e:
            self.logger.warning(f"Не удалось дождаться заголовка на {url}: {e}. Страница может быть невалидной.")
            return None

        # --- Заголовок ---
        title_el = await page.query_selector(sel['title'])
        data['title'] = await self._safe_get_text(title_el, 'title', url)
        if not data['title']:
             self.logger.warning(f"Не найден заголовок (вторая попытка) на {url}. Пропуск.")
             return None # Заголовок обязателен

        # --- Фильтрация по ключевым словам (если нужно) ---
        title_lower = data['title'].lower()
        if any(keyword in title_lower for keyword in self.blacklist_keywords):
            self.logger.debug(f"Пропуск (черный список): {data['title']} ({url})")
            return None

        # --- Цена ---
        price_el = await page.query_selector(sel['price'])
        data['price'] = await self._safe_get_text(price_el, 'price', url)
        if not data['price']: data['price'] = "N/A"

        # --- Локация ---
        location_el = await page.query_selector(sel['location'])
        data['location'] = await self._safe_get_text(location_el, 'location', url)
        if not data['location']: data['location'] = "N/A"

        # --- Площадь (из характеристик) ---
        data['area'] = "N/A"
        try:
            features_list_el = await page.query_selector(sel['features_list'])
            if features_list_el:
                feature_items = await features_list_el.query_selector_all(sel['feature_item'])
                area_found = False
                for item in feature_items:
                    item_text = await item.inner_text()
                    item_text_lower = item_text.lower()
                    # Ищем 'rea total' или 'superficie total'
                    if "rea total" in item_text_lower or "superficie total" in item_text_lower:
                        value_el = await item.query_selector('strong') # Значение обычно в strong
                        area_text = await self._safe_get_text(value_el, 'feature_value (area)', url)
                        if area_text:
                            # Проверяем, есть ли м² или га
                            if re.search(r'(m²|ha)', area_text, re.IGNORECASE):
                                data['area'] = area_text
                                self.logger.debug(f"Площадь найдена в характеристиках: {data['area']}")
                                area_found = True
                                break # Нашли, выходим
                            else:
                                 self.logger.debug(f"Найден текст площади '{area_text}', но без единиц (m²/ha).")
                if not area_found:
                     self.logger.debug(f"Площадь не найдена в списке характеристик '{sel['features_list']}'.")
            else:
                self.logger.debug(f"Не найден список характеристик '{sel['features_list']}'.")
        except Exception as e:
            self.logger.warning(f"Ошибка при извлечении площади из характеристик: {e}")

        # --- Изображение ---
        data['image_url'] = None
        try:
            gallery_el = await page.query_selector(sel['image_gallery'])
            if gallery_el:
                 img_el = await gallery_el.query_selector(sel['image'])
                 img_src = await self._safe_get_attribute(img_el, 'src', 'image', url)
                 if img_src and img_src.startswith('http'):
                     try:
                         data['image_url'] = HttpUrl(img_src)
                         self.logger.debug(f"Найдено изображение: {data['image_url']}")
                     except Exception:
                          self.logger.debug(f"Невалидный URL изображения: {img_src}")
                 else:
                      self.logger.debug(f"Атрибут src пустой или не http: {img_src}")
            else:
                 self.logger.debug(f"Не найдена галерея изображений '{sel['image_gallery']}'")
        except Exception as e:
            self.logger.warning(f"Ошибка при извлечении изображения: {e}")


        # --- Описание ---
        desc_el = await page.query_selector(sel['description_content'])
        # Собираем текст из всех <p> внутри контейнера описания
        description_text = ""
        if desc_el:
             paragraphs = await desc_el.query_selector_all('p')
             desc_parts = [await self._safe_get_text(p, 'description_paragraph', url) for p in paragraphs]
             description_text = "\n".join(filter(None, desc_parts)) # Объединяем через перенос строки
        
        # Используем описание, если оно есть, иначе fallback на заголовок
        data['description'] = description_text if description_text else data['title']
        
        # --- Удобства (Utilities / Extras) ---
        # Пытаемся извлечь из секции amenities
        utilities_list = []
        try:
             amenities_section_el = await page.query_selector(sel['amenities_section'])
             if amenities_section_el:
                 amenity_items = await amenities_section_el.query_selector_all(sel['amenity_item'])
                 for item in amenity_items:
                     amenity_text = await self._safe_get_text(item, 'amenity_item', url)
                     if amenity_text:
                         utilities_list.append(amenity_text)
                 self.logger.debug(f"Найдено удобств: {len(utilities_list)}")
             else:
                  self.logger.debug(f"Не найдена секция удобств '{sel['amenities_section']}'")
        except Exception as e:
            self.logger.warning(f"Ошибка при извлечении удобств: {e}")
            
        data['utilities'] = ", ".join(utilities_list) if utilities_list else "Не указано"


        # --- Значения по умолчанию ---
        data["deal_type"] = "Продажа" # Т.к. мы ищем в разделе venta
        data["posted_date"] = None # Дату сложно извлечь reliably

        self.logger.debug(f"Извлечены данные со страницы объявления {url}: {data}")
        return data

    async def _safe_get_attribute(self, element: Optional[ElementHandle], attribute_name: str, selector_name: str, url: str) -> str:
        """Безопасно получает значение атрибута элемента."""
        if element:
            try:
                # Используем await для асинхронного вызова get_attribute
                attr_value = await element.get_attribute(attribute_name)
                # Проверяем, что значение не None перед вызовом strip()
                return attr_value.strip() if attr_value else ""
            except Exception as e:
                self.logger.debug(f"Не удалось получить значение атрибута '{attribute_name}' для селектора '{selector_name}' на {url}: {e}")
        return ""

    async def _delay(self):
        """Задержка между запросами."""
        await asyncio.sleep(random.uniform(*self.request_delay))

    async def _extract_data_from_detail_page(self, page: Page, listing: Listing) -> Optional[Listing]:
        """Извлекает детальную информацию, используя существующий метод _extract_data_from_listing_page,
           и обновляет переданный объект Listing.
        """
        self.logger.debug(f"Вызов _extract_data_from_detail_page для {listing.url}")
        url_str = str(listing.url)
        # Вызываем существующий метод, который возвращает Dict
        data_dict = await self._extract_data_from_listing_page(page, url_str)

        if data_dict:
            self.logger.debug(f"Получены данные из _extract_data_from_listing_page для {url_str}")
            try:
                # Обновляем поля объекта Listing из словаря
                for key, value in data_dict.items():
                    if hasattr(listing, key):
                        setattr(listing, key, value)
                    else:
                        if key not in ['source', 'url']: # Игнорируем уже существующие и не относящиеся к модели
                             self.logger.debug(f"Ключ '{key}' из data_dict отсутствует в модели Listing.")
                
                listing.date_scraped = self.now_utc()
                
                self.logger.info(f"Объект Listing обновлен данными для {listing.url}")
                return listing
            except Exception as e:
                self.logger.error(f"Ошибка при обновлении объекта Listing для {url_str}: {e}", exc_info=True)
                return None
        else:
            self.logger.warning(f"_extract_data_from_listing_page не вернул данные для {url_str}")
            return None

    async def _normalize_data(self, data: Dict[str, Any], url: str) -> Optional[Listing]:
        # Реализация нормализации данных для InfoCasas
        # ... (логика нормализации) ...
        pass # Заглушка

    async def _get_listing_urls(self, page_content: str) -> List[str]:
        # Реализация получения URL со страницы списка InfoCasas
        # ... (логика парсинга HTML) ...
        pass # Заглушка

    async def _extract_listing_details(self, page: Page, url: str) -> Optional[Listing]:
        # Реализация получения деталей со страницы объявления InfoCasas
        # ... (логика парсинга страницы деталей) ...
        pass # Заглушка

    # ... остальные методы ...

    # ... другие методы ... 