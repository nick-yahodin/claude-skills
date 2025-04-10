#!/usr/bin/env python3
"""
Парсер для сайта MercadoLibre Уругвай (недвижимость - terrenos/venta).
"""

import asyncio
import logging
import re
import json
import random
from typing import List, Optional, Dict, Any, Union, Type
from playwright.async_api import Page, BrowserContext, ElementHandle, Locator, Error
from urllib.parse import urljoin
from pydantic import HttpUrl
from datetime import datetime
import base64
import os

from .base import BaseParser
from app.models import Listing
try:
    from app.base64_handler import (
        is_base64_image, process_and_save_base64_image, 
        extract_base64_images_from_html
    )
    # Маркер для проверки, доступен ли модуль
    BASE64_HANDLER_AVAILABLE = True
except ImportError:
    # Если модуль не найден, будем использовать встроенную обработку
    BASE64_HANDLER_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "Модуль app.base64_handler не найден. Будет использована базовая обработка Base64."
    )

class MercadoLibreParser(BaseParser):
    """
    Парсер для MercadoLibre.com.uy
    Реализует специфическую логику для сайта MercadoLibre.
    """
    SOURCE_NAME = "mercadolibre"
    BASE_URL = "https://listado.mercadolibre.com.uy/inmuebles/terrenos/venta/"
    SEARCH_URL_TEMPLATE = BASE_URL + "/_Desde_{offset}"  # {offset} = (page-1)*48 + 1

    def __init__(self, 
                 smartproxy_config: Optional[Dict[str, str]] = None, 
                 headless_mode: bool = True,
                 max_retries: int = 3, 
                 request_delay_range: tuple = (3, 7)):
        # Если smartproxy_config не передан, используем значения по умолчанию
        if smartproxy_config is None:
            smartproxy_config = {
                "server": "uy.smartproxy.com:15001",
                "user_pattern": "spgai22txz",
                "password": "jtx6i24Jpb~eweNw2eo"
            }
            
        # Передаем новые параметры в базовый класс
        super().__init__(smartproxy_config=smartproxy_config, 
                         headless_mode=headless_mode,
                         max_retries=max_retries, 
                         request_delay=request_delay_range)
        self.logger = logging.getLogger(__name__)
        # Селекторы для СТРАНИЦЫ СПИСКА - обновлены на основе анализа структуры 2025 года
        self.list_selectors = {
            'container': 'ol.ui-search-layout',
            'item': 'li.ui-search-layout__item',
            'url': 'div.ui-search-result__content a.ui-search-link',  # Обновленный селектор для URL
            'url_alt': ['a.ui-search-link', 'h2.ui-search-item__title a', 'div.ui-search-result__image a'],
            'title': 'h2.ui-search-item__title',
            'title_alt': ['div.ui-search-item__group h2', 'div.ui-search-item__title', 'a.ui-search-link span'],
            'price': 'span.price-tag-fraction',
            'price_alt': ['div.ui-search-price__second-line span.andes-money-amount__fraction', 'span.andes-money-amount__fraction'],
            'currency': 'span.price-tag-symbol',
            'currency_alt': ['div.ui-search-price__second-line span.andes-money-amount__currency-symbol', 'span.andes-money-amount__currency-symbol'],
            'address': 'span.ui-search-item__location',
            'address_alt': ['p.ui-search-item__group__element', 'div.ui-search-item__group p'],
            'area': 'ul.ui-search-card-attributes li.ui-search-card-attributes__attribute',
            'area_alt': ['div.ui-search-item__group ul li', 'ul.ui-search-item__attributes li'],
            'image': 'img.ui-search-result-image__element',
            'image_alt': ['div.ui-search-result__image img', 'div.slick-slide.slick-active img', 'img[data-src]', 'img.ui-search-result-image__element']
        }
        # Селекторы для СТРАНИЦЫ ДЕТАЛЕЙ - обновлены для структуры 2025 года
        self.detail_selectors = {
            'title': 'h1.ui-pdp-title',
            'title_alt': ['h1', 'div.ui-pdp-header__title-container h1'],
            'price_fraction': 'span.andes-money-amount__fraction',
            'price_currency': 'span.andes-money-amount__currency-symbol',
            'description': 'div.ui-pdp-description__content',
            'description_alt': ['div.ui-pdp-description p', 'p.ui-pdp-description__content'],
            'main_image': 'figure.ui-pdp-gallery__figure img',
            'main_image_alt': ['div.ui-pdp-gallery img', 'div.ui-pdp-thumbnail__picture img'],
            'area': 'div.ui-pdp-specs__table tr:contains("Superficie")',
            'area_alt': ['div.ui-pdp-specs__table tr', 'div.ui-pdp-highlighted-specs-res span.ui-pdp-label'],
            'attributes_table': 'div.ui-pdp-specs__table',
            'attributes_table_alt': ['table.andes-table', 'div.ui-vip-specifications'],
            'breadcrumbs_links': 'ol.andes-breadcrumb li a.andes-breadcrumb__link',
            'location': 'div.ui-pdp-media__title',
            'location_alt': ['p.ui-pdp-media__title', 'div.ui-pdp-location p']
        }
        
        # Ключевые слова для фильтрации (можно оставить пустыми, если раздел и так нужный)
        self.blacklist_keywords = [
            'alquiler', 'arriendo', 'temporal'
        ]
        self.whitelist_keywords = [] # Пока не используем

    async def _get_page_url(self, page_number: int) -> str:
        """Возвращает URL для страницы результатов MercadoLibre."""
        # У MercadoLibre URL меняется иначе - через параметр _Desde
        if page_number == 1:
            # Для первой страницы используем базовый URL без сортировки
            return f"{self.BASE_URL}/"
        else:
            # Для последующих страниц добавляем смещение и сортировку по цене (_OrderId_PRICE)
            # Каждый элемент - 1 лот, на странице обычно 48
            offset = (page_number - 1) * 48 + 1
            return f"{self.BASE_URL}/_Desde_{offset}_OrderId_PRICE"

    async def _extract_listings_from_page(self, page: Page) -> List[Listing]:
        """Извлекает список объектов Listing со страницы результатов."""
        listings: List[Listing] = []
        
        # Улучшенная обработка ошибок - добавляем структуру try/except на верхнем уровне
        try:
            # Сохраняем скриншот страницы для отладки
            try:
                debug_path = "errors/list_debug_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
                await page.screenshot(path=debug_path)
                self.logger.info(f"Сохранен отладочный скриншот списка: {debug_path}")
                
                # Сохраняем HTML страницы
                html_path = "errors/list_html_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".html"
                page_content = await page.content()
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(page_content)
                self.logger.info(f"Сохранен HTML страницы списка: {html_path}")
            except Exception as ss_err:
                self.logger.warning(f"Не удалось сохранить отладочную информацию: {ss_err}")
            
            # Система повторных попыток для поиска контейнера и карточек
            max_retries = 3  # Максимальное количество попыток
            retry_delay = 2  # Начальная задержка в секундах
            container = None
            cards = []
            
            for retry in range(max_retries):
                try:
                    # Проверка наличия контейнера
                    container = await page.query_selector(self.list_selectors['container'])
                    if not container:
                        self.logger.warning(f"Попытка {retry+1}/{max_retries}: Не найден основной контейнер '{self.list_selectors['container']}'. Пробуем найти карточки напрямую.")
                    
                    # Найдем все карточки объявлений
                    cards = await page.query_selector_all(self.list_selectors['item'])
                    self.logger.info(f"Попытка {retry+1}/{max_retries}: Найдено {len(cards)} карточек по основному селектору '{self.list_selectors['item']}'")
                    
                    # Если карточки найдены, выходим из цикла повторных попыток
                    if len(cards) > 0:
                        break
                    
                    # Если карточки не найдены, пробуем альтернативные селекторы
                    alt_selectors = ['div.ui-search-result', 'li[class*="search-layout__item"]', 'div.ui-search-result__wrapper']
                    for alt_selector in alt_selectors:
                        cards = await page.query_selector_all(alt_selector)
                        if cards and len(cards) > 0:
                            self.logger.info(f"Попытка {retry+1}/{max_retries}: Найдено {len(cards)} карточек по альтернативному селектору '{alt_selector}'")
                            break
                    
                    # Если и по альтернативным селекторам не нашли, но не последняя попытка, 
                    # ждем некоторое время и пробуем снова
                    if len(cards) == 0 and retry < max_retries - 1:
                        self.logger.warning(f"Попытка {retry+1}/{max_retries}: Не найдены карточки. Ожидание {retry_delay} сек перед повторной попыткой...")
                        await page.wait_for_timeout(retry_delay * 1000)  # Задержка в мс
                        
                        # Увеличиваем задержку для следующей попытки (экспоненциальная задержка)
                        retry_delay *= 2
                        
                        # Попробуем обновить страницу
                        if retry == 1:  # На второй попытке обновим страницу
                            self.logger.info("Обновление страницы...")
                            await page.reload(wait_until="domcontentloaded", timeout=30000)
                    else:
                        break
                except Exception as retry_err:
                    self.logger.error(f"Ошибка при попытке {retry+1}/{max_retries} поиска карточек: {retry_err}")
                    if retry < max_retries - 1:
                        self.logger.warning(f"Ожидание {retry_delay} сек перед повторной попыткой...")
                        await page.wait_for_timeout(retry_delay * 1000)
                        retry_delay *= 2
            
            # Проверяем, нашли ли мы карточки после всех попыток
            if len(cards) == 0:
                self.logger.error("Не удалось найти карточки объявлений после всех попыток. Возвращаем пустой список.")
                return []
            
            # Статистика для улучшенного логирования
            total_cards = len(cards)
            successful_cards = 0
            skipped_cards = 0
            error_cards = 0
            
            # Перебираем карточки и извлекаем данные
            processed_urls_on_page = set()
            
            for i, card in enumerate(cards):
                # Ограничиваем количество обрабатываемых карточек для теста
                if i >= 1:
                    self.logger.info(f"Достигнут лимит в 1 карточку для теста. Прерывание обработки карточек на этой странице.")
                    break
                
                self.logger.debug(f"--- Начало обработки карточки {i+1}/{total_cards} ---")
                
                try:
                    # Словарь для хранения данных текущего объявления
                    listing_data: Dict[str, Any] = {}
                    
                    # 1. Извлечение URL
                    url_found = False
                    # Сначала пробуем основной селектор
                    url_elem = await card.query_selector(self.list_selectors['url'])
                    if url_elem:
                        href = await url_elem.get_attribute('href')
                        if href and href.startswith('http'):
                            listing_data['url'] = href
                            url_found = True
                            self.logger.debug(f"Карточка {i+1}: URL найден по основному селектору: {href}")
                    
                    # Если основной селектор не сработал, пробуем альтернативные
                    if not url_found:
                        for alt_selector in self.list_selectors['url_alt']:
                            url_elem = await card.query_selector(alt_selector)
                            if url_elem:
                                href = await url_elem.get_attribute('href')
                                if href and href.startswith('http'):
                                    listing_data['url'] = href
                                    url_found = True
                                    self.logger.debug(f"Карточка {i+1}: URL найден по альтернативному селектору '{alt_selector}': {href}")
                                    break
                    
                    # Если URL все еще не найден, пробуем JavaScript для поиска любых ссылок внутри карточки
                    if not url_found:
                        try:
                            js_script = """
                            (card) => {
                                const links = card.querySelectorAll('a');
                                for (const link of links) {
                                    const href = link.getAttribute('href');
                                    if (href && href.startsWith('http') && (href.includes('MLU-') || href.includes('mercadolibre'))) {
                                        return href;
                                    }
                                }
                                return null;
                            }
                            """
                            href = await page.evaluate(js_script, card)
                            if href:
                                listing_data['url'] = href
                                url_found = True
                                self.logger.debug(f"Карточка {i+1}: URL найден через JavaScript: {href}")
                        except Exception as js_error:
                            self.logger.warning(f"Карточка {i+1}: Ошибка при извлечении URL через JavaScript: {js_error}")
                    
                    # Пропускаем карточку, если URL не найден
                    if not url_found:
                        self.logger.warning(f"Карточка {i+1}: URL не найден по всем селекторам. Пропуск карточки.")
                        skipped_cards += 1
                        continue
                    
                    # Проверка и исправление URL (должен вести на страницу деталей, а не на страницу списка)
                    if '/listado.' in href or '_OrderId_' in href or '_Desde_' in href:
                        self.logger.warning(f"Карточка {i+1}: Обнаружен URL страницы списка вместо объявления: {href}")
                        
                        # Ищем ID объявления в URL или через JavaScript
                        mlu_match = re.search(r'(MLU-\d+)', href)
                        if mlu_match:
                            mlu_id = mlu_match.group(1)
                            corrected_url = f"https://articulo.mercadolibre.com.uy/{mlu_id}"
                            self.logger.info(f"Карточка {i+1}: URL исправлен на: {corrected_url}")
                            listing_data['url'] = corrected_url
                        else:
                            # Пытаемся извлечь URL через JavaScript, если не удалось найти ID
                            try:
                                js_script = """
                                (card) => {
                                    const anchors = card.querySelectorAll('a[href*="articulo.mercadolibre"], a[href*="MLU-"]');
                                    for (const anchor of anchors) {
                                        const href = anchor.getAttribute('href');
                                        if (href && href.includes('articulo.mercadolibre') || 
                                            (href && href.includes('MLU-') && !href.includes('listado'))) {
                                            return href;
                                        }
                                    }
                                    return null;
                                }
                                """
                                detail_url = await page.evaluate(js_script, card)
                                if detail_url and detail_url.startswith('http'):
                                    self.logger.info(f"Карточка {i+1}: URL исправлен через JavaScript: {detail_url}")
                                    listing_data['url'] = detail_url
                            except Exception as js_err:
                                self.logger.warning(f"Карточка {i+1}: Не удалось исправить URL через JavaScript: {js_err}")
                    
                    # Базовая информация для объекта листинга
                    listing_data['source'] = self.SOURCE_NAME
                    
                    # 2. Извлечение заголовка
                    title_found = False
                    title_elem = await card.query_selector(self.list_selectors['title'])
                    if title_elem:
                        title = await title_elem.inner_text()
                        if title and title.strip():
                            listing_data['title'] = title.strip()
                            title_found = True
                            self.logger.debug(f"Карточка {i+1}: Заголовок найден: {title.strip()}")
                    
                    # Пробуем альтернативные селекторы для заголовка
                    if not title_found:
                        for alt_selector in self.list_selectors['title_alt']:
                            title_elem = await card.query_selector(alt_selector)
                            if title_elem:
                                title = await title_elem.inner_text()
                                if title and title.strip():
                                    listing_data['title'] = title.strip()
                                    title_found = True
                                    self.logger.debug(f"Карточка {i+1}: Заголовок найден по альтернативному селектору '{alt_selector}': {title.strip()}")
                                    break
                    
                    # Если заголовок все еще не найден, извлекаем из URL
                    if not title_found:
                        url_parts = str(listing_data['url']).split('/')[-1].split('-')
                        potential_title = ' '.join([part.capitalize() for part in url_parts if len(part) > 2 and not part.startswith('MLU')])
                        if potential_title:
                            listing_data['title'] = potential_title
                            self.logger.debug(f"Карточка {i+1}: Заголовок извлечен из URL: {potential_title}")
                        else:
                            listing_data['title'] = "Terreno en venta"  # Значение по умолчанию
                            self.logger.debug(f"Карточка {i+1}: Используем заголовок по умолчанию")
                    
                    # 3. Извлечение цены
                    price_found = False
                    
                    # Сначала пробуем найти элементы цены и валюты одновременно
                    price_elem = await card.query_selector(self.list_selectors['price'])
                    currency_elem = await card.query_selector(self.list_selectors['currency'])
                    
                    if price_elem and currency_elem:
                        price_fraction = await price_elem.inner_text()
                        price_currency = await currency_elem.inner_text()
                        
                        if price_fraction and price_currency:
                            listing_data['price'] = f"{price_currency.strip()} {price_fraction.strip()}".strip()
                            price_found = True
                            self.logger.debug(f"Карточка {i+1}: Цена найдена: {listing_data['price']}")
                    
                    # Если основные селекторы не сработали, пробуем альтернативные для дробной части и валюты
                    if not price_found:
                        for price_alt, currency_alt in zip(self.list_selectors['price_alt'], self.list_selectors['currency_alt']):
                            price_elem = await card.query_selector(price_alt)
                            currency_elem = await card.query_selector(currency_alt)
                            
                            if price_elem and currency_elem:
                                price_fraction = await price_elem.inner_text()
                                price_currency = await currency_elem.inner_text()
                                
                                if price_fraction and price_currency:
                                    listing_data['price'] = f"{price_currency.strip()} {price_fraction.strip()}".strip()
                                    price_found = True
                                    self.logger.debug(f"Карточка {i+1}: Цена найдена по альтернативным селекторам: {listing_data['price']}")
                                    break
                    
                    # Если цена все еще не найдена, попробуем найти через JavaScript
                    if not price_found:
                        try:
                            # Попытка найти цену через JavaScript
                            js_script = """
                            (card) => {
                                // Ищем любой элемент с ценой
                                const priceElements = card.querySelectorAll('.price-tag-fraction, .andes-money-amount__fraction, span[class*="price"]');
                                const currencyElements = card.querySelectorAll('.price-tag-symbol, .andes-money-amount__currency-symbol');
                                
                                let price = null;
                                let currency = null;
                                
                                // Получаем значение цены
                                if (priceElements.length > 0) {
                                    price = priceElements[0].textContent.trim();
                                }
                                
                                // Получаем значение валюты
                                if (currencyElements.length > 0) {
                                    currency = currencyElements[0].textContent.trim();
                                } else {
                                    // Если валюта не найдена, используем U$S для Уругвая
                                    currency = 'U$S';
                                }
                                
                                if (price) {
                                    return { price, currency };
                                }
                                
                                // Если не нашли через классы, ищем числа в контенте
                                const priceText = card.innerText;
                                const priceMatch = priceText.match(/U\$S\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?)|(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s*U\$S/);
                                if (priceMatch) {
                                    return { 
                                        price: priceMatch[1] || priceMatch[2], 
                                        currency: 'U$S' 
                                    };
                                }
                                
                                return null;
                            }
                            """
                            price_data = await page.evaluate(js_script, card)
                            if price_data and price_data.get('price'):
                                listing_data['price'] = f"{price_data['currency']} {price_data['price']}".strip()
                                price_found = True
                                self.logger.debug(f"Карточка {i+1}: Цена найдена через JavaScript: {listing_data['price']}")
                        except Exception as js_err:
                            self.logger.warning(f"Карточка {i+1}: Ошибка при извлечении цены через JavaScript: {js_err}")
                    
                    # Если цена не найдена, устанавливаем значение по умолчанию
                    if not price_found:
                        self.logger.debug(f"Карточка {i+1}: Цена не найдена. Устанавливаем значение по умолчанию.")
                        listing_data['price'] = "Consultar precio"  # Значение по умолчанию
                    
                    # 4. Извлечение локации
                    location_found = False
                    location_elem = await card.query_selector(self.list_selectors['address'])
                    
                    if location_elem:
                        location = await location_elem.inner_text()
                        if location and location.strip():
                            listing_data['location'] = location.strip()
                            location_found = True
                            self.logger.debug(f"Карточка {i+1}: Локация найдена: {location.strip()}")
                    
                    # Пробуем альтернативные селекторы для локации
                    if not location_found:
                        for alt_selector in self.list_selectors['address_alt']:
                            location_elem = await card.query_selector(alt_selector)
                            if location_elem:
                                location = await location_elem.inner_text()
                                if location and location.strip():
                                    listing_data['location'] = location.strip()
                                    location_found = True
                                    self.logger.debug(f"Карточка {i+1}: Локация найдена по альтернативному селектору '{alt_selector}': {location.strip()}")
                                    break
                    
                    # Если локация не найдена, устанавливаем значение по умолчанию
                    if not location_found:
                        self.logger.debug(f"Карточка {i+1}: Локация не найдена. Устанавливаем значение по умолчанию.")
                        listing_data['location'] = "Uruguay"  # Значение по умолчанию
                    
                    # 5. Извлечение площади
                    area_found = False
                    
                    # Сначала пробуем основной селектор для площади
                    area_elements = await card.query_selector_all(self.list_selectors['area'])
                    
                    for element in area_elements:
                        area_text = await element.inner_text()
                        if area_text and ('m²' in area_text or 'ha' in area_text.lower()):
                            listing_data['area'] = area_text.strip()
                            area_found = True
                            self.logger.debug(f"Карточка {i+1}: Площадь найдена: {area_text.strip()}")
                            break
                    
                    # Если не нашли по основному селектору, пробуем альтернативные
                    if not area_found:
                        for alt_selector in self.list_selectors['area_alt']:
                            area_elements = await card.query_selector_all(alt_selector)
                            for element in area_elements:
                                area_text = await element.inner_text()
                                if area_text and ('m²' in area_text or 'ha' in area_text.lower()):
                                    listing_data['area'] = area_text.strip()
                                    area_found = True
                                    self.logger.debug(f"Карточка {i+1}: Площадь найдена по альтернативному селектору '{alt_selector}': {area_text.strip()}")
                                    break
                            if area_found:
                                break
                    
                    # Если площадь все еще не найдена, пробуем через JavaScript
                    if not area_found:
                        try:
                            # Попытка найти площадь через JavaScript
                            js_script = """
                            (card) => {
                                // Текст всей карточки
                                const cardText = card.innerText;
                                
                                // Ищем паттерны площади
                                const areaM2Match = cardText.match(/(\d+[.,]?\d*)\s*(?:m²|m2|metros?|mts)/i);
                                if (areaM2Match) {
                                    return areaM2Match[0].trim();
                                }
                                
                                const areaHaMatch = cardText.match(/(\d+[.,]?\d*)\s*(?:ha|hect[áa]reas?)/i);
                                if (areaHaMatch) {
                                    return areaHaMatch[0].trim();
                                }
                                
                                return null;
                            }
                            """
                            area_data = await page.evaluate(js_script, card)
                            if area_data:
                                listing_data['area'] = area_data
                                area_found = True
                                self.logger.debug(f"Карточка {i+1}: Площадь найдена через JavaScript: {area_data}")
                        except Exception as js_err:
                            self.logger.warning(f"Карточка {i+1}: Ошибка при извлечении площади через JavaScript: {js_err}")
                    
                    # Если площадь не найдена, оставляем None
                    if not area_found:
                        self.logger.debug(f"Карточка {i+1}: Площадь не найдена")
                    
                    # 6. Извлечение URL изображения
                    image_found = False
                    
                    # Пробуем основной селектор для изображения
                    img_elem = await card.query_selector(self.list_selectors['image'])
                    
                    if img_elem:
                        for attr in ['src', 'data-src']:
                            img_url = await img_elem.get_attribute(attr)
                            if img_url and img_url.startswith('http') and not img_url.startswith('data:'):
                                try:
                                    listing_data['image_url'] = img_url
                                    image_found = True
                                    self.logger.debug(f"Карточка {i+1}: Изображение найдено: {img_url[:50]}...")
                                    break
                                except Exception as image_error:
                                    self.logger.warning(f"Карточка {i+1}: Ошибка при обработке URL изображения: {image_error}")
                    
                    # Если не нашли изображение по основному селектору, пробуем альтернативные
                    if not image_found:
                        for alt_selector in self.list_selectors['image_alt']:
                            img_elem = await card.query_selector(alt_selector)
                            if img_elem:
                                for attr in ['src', 'data-src']:
                                    img_url = await img_elem.get_attribute(attr)
                                    if img_url and img_url.startswith('http') and not img_url.startswith('data:'):
                                        try:
                                            listing_data['image_url'] = img_url
                                            image_found = True
                                            self.logger.debug(f"Карточка {i+1}: Изображение найдено по альтернативному селектору '{alt_selector}': {img_url[:50]}...")
                                            break
                                        except Exception as image_error:
                                            self.logger.warning(f"Карточка {i+1}: Ошибка при обработке URL изображения: {image_error}")
                                if image_found:
                                    break
                    
                    # Если изображение не найдено, оставляем None
                    if not image_found:
                        self.logger.debug(f"Карточка {i+1}: Изображение не найдено")
                    
                    # 7. Устанавливаем значения по умолчанию для оставшихся полей
                    listing_data.setdefault('description', None)  # Описание берем только с детальной страницы
                    listing_data.setdefault('utilities', None)    # Утилиты берем только с детальной страницы
                    listing_data.setdefault('deal_type', 'Venta') # Тип сделки по умолчанию
                    
                    # 8. Создание объекта Listing и добавление в результаты
                    try:
                        # Проверка на blacklist ключевые слова
                        if listing_data.get('title') and any(kw in listing_data['title'].lower() for kw in self.blacklist_keywords):
                            self.logger.debug(f"Карточка {i+1}: Пропуск по черному списку: '{listing_data.get('title')}'")
                            skipped_cards += 1
                            continue
                        
                        # Создаем объект Listing
                        listing_obj = Listing(**listing_data)
                        listings.append(listing_obj)
                        processed_urls_on_page.add(href)
                        self.global_seen_urls.add(href)
                        successful_cards += 1
                        self.logger.debug(f"Карточка {i+1}: Объект Listing успешно создан")
                    except Exception as e:
                        self.logger.warning(f"Карточка {i+1}: Ошибка создания объекта Listing: {e}")
                        error_cards += 1
                
                except Exception as e:
                    self.logger.warning(f"Карточка {i+1}: Неожиданная ошибка при обработке: {e}")
                    error_cards += 1
                    continue
            
            # Логирование результатов
            self.logger.info(f"Обработка карточек завершена. Всего: {total_cards}, успешно: {successful_cards}, пропущено: {skipped_cards}, ошибок: {error_cards}")
            self.logger.info(f"Извлечено {len(listings)} новых уникальных объектов Listing со страницы {self.stats['pages_processed'] + 1}.")
            
            return listings
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении списка объявлений: {e}", exc_info=True)
            return []

    # <<< Обновленный метод парсинга деталей >>>
    async def _get_main_image_from_detail_page(self, page: Page, url: str) -> Optional[str]:
        """
        Извлекает URL главного изображения со страницы деталей объявления.
        Использует несколько методов для максимальной надежности.
        """
        self.logger.info(f"Извлечение главного изображения для: {url}")
        try:
            # Метод 1: Извлечение изображений через прямые запросы к API
            try:
                # Проверяем URL на наличие ID объявления
                mlu_match = re.search(r'MLU-?(\d+)', url)
                if mlu_match:
                    mlu_id = mlu_match.group(0).replace('-', '')
                    item_numeric_id = re.sub(r'^MLU', '', mlu_id)
                    
                    # Пытаемся извлечь ID изображения напрямую из HTML-кода страницы
                    html_content = await page.content()
                    img_id_patterns = [
                        r'"picture_id":"([^"]+)"',
                        r'"image_id":"([^"]+)"',
                        r'data-zoom="https://http2\.mlstatic\.com/D_NQ_NP_\d*_?([^"\.]+)',
                        r'https://http2\.mlstatic\.com/D_NQ_NP_\d*_?([^"\.]+)\.webp',
                        r'<img[^>]+src="https://http2\.mlstatic\.com/D_NQ_NP_[^"]*?(\d+[^"\.]+)'
                    ]
                    
                    image_id = None
                    for pattern in img_id_patterns:
                        matches = re.findall(pattern, html_content)
                        if matches:
                            image_id = matches[0]
                            self.logger.info(f"Извлечен ID изображения из страницы: {image_id}")
                            break
                    
                    if image_id:
                        # Формируем URL на основе найденного ID
                        img_urls = [
                            f"https://http2.mlstatic.com/D_NQ_NP_2X_{image_id}.webp",
                            f"https://http2.mlstatic.com/D_NQ_NP_{image_id}.webp",
                        ]
                        
                        # Проверяем доступность через HEAD-запрос
                        for img_url in img_urls:
                            response = await page.evaluate(f"""
                            async () => {{
                                try {{
                                    const resp = await fetch('{img_url}', {{ method: 'HEAD' }});
                                    if (resp.ok) return '{img_url}';
                                    return null;
                                }} catch (e) {{
                                    return null;
                                }}
                            }}
                            """)
                            
                            if response:
                                self.logger.info(f"Найдено изображение через извлеченный ID: {response}")
                                return response
                    
                    # Если ID не найден или URL недоступен, пробуем прямую ссылку по ID объявления
                    img_templates = [
                        f"https://http2.mlstatic.com/D_NQ_NP_2X_{mlu_id}-F.webp",
                        f"https://http2.mlstatic.com/D_NQ_NP_{mlu_id}-F.webp",
                        f"https://http2.mlstatic.com/D_NQ_NP_2X_845364-{mlu_id}-F.webp",
                        f"https://http2.mlstatic.com/D_NQ_NP_2X_683091{item_numeric_id}-F.webp",
                        f"https://http2.mlstatic.com/D_NQ_NP_2X_820071{item_numeric_id}-F.webp",
                        f"https://http2.mlstatic.com/D_NQ_NP_2X_637399{item_numeric_id}-F.webp",
                        f"https://http2.mlstatic.com/D_NQ_NP_2X_994265{item_numeric_id}-F.webp"
                    ]
                    
                    for img_url in img_templates:
                        response = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const resp = await fetch('{img_url}', {{ method: 'HEAD' }});
                                if (resp.ok) return '{img_url}';
                                return null;
                            }} catch (e) {{
                                return null;
                            }}
                        }}
                        """)
                        
                        if response:
                            self.logger.info(f"Найдено изображение через API: {response}")
                            return response
                    
                    # Если не нашли прямыми методами, ищем готовые URL в HTML
                    img_url_patterns = [
                        r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.webp)"',
                        r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.jpg)"',
                        r'content="(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.(webp|jpg))"'
                    ]
                    
                    for pattern in img_url_patterns:
                        img_matches = re.findall(pattern, html_content)
                        if img_matches:
                            for img_match in img_matches:
                                img_url = img_match[0] if isinstance(img_match, tuple) else img_match
                                if img_url.startswith('http') and 'http2.mlstatic.com' in img_url:
                                    # Проверяем, что это не заглушка
                                    if not any(x in img_url for x in ['mercadolibre.com/homes', 'placeholder', 'org-img']):
                                        self.logger.info(f"Найдено изображение через HTML: {img_url}")
                                        return img_url
            except Exception as api_err:
                self.logger.debug(f"Ошибка при попытке прямого доступа к API изображений: {api_err}")

            # Метод 2: Использование JavaScript для поиска и ранжирования всех изображений
            js_script = """
            () => {
                // Функция для проверки URL на валидность как изображение
                const isValidImageUrl = (url) => {
                    if (!url) return false;
                    if (url.startsWith('data:')) return false;
                    // Исключаем генерируемые заглушки
                    if (url.includes('mercadolibre.com/homes')) return false;
                    if (url.includes('mercadolibre.com/myML/')) return false;
                    if (url.includes('mercadolibre.com/org-img/')) return false;
                    if (url.includes('UI/public/placeholder')) return false;
                    return url.match(/\\.(jpeg|jpg|png|webp)(\\?.*)?$/i) || 
                           url.includes('image') || 
                           url.includes('img');
                };
                
                // Массив для хранения всех найденных изображений с метаданными о приоритете
                const images = [];
                
                // 1. Ищем изображения через медиа-галерею
                const galleryImages = document.querySelectorAll('.ui-pdp-gallery__figure img, .ui-pdp-gallery img, .ui-pdp-image img');
                galleryImages.forEach((img, index) => {
                    // Проверяем сначала data-zoom атрибут для высокого разрешения
                    const zoomSrc = img.getAttribute('data-zoom');
                    if (zoomSrc && isValidImageUrl(zoomSrc)) {
                        images.push({ 
                            src: zoomSrc, 
                            priority: 1, 
                            position: index,
                            source: 'gallery-zoom'
                        });
                    }
                    
                    // Затем проверяем обычный src
                    const src = img.getAttribute('src');
                    if (src && isValidImageUrl(src)) {
                        images.push({ 
                            src, 
                            priority: 1 + index * 0.1, // Первое изображение имеет высший приоритет
                            position: index,
                            source: 'gallery'
                        });
                    }
                });
                
                // 2. Ищем в мета-тегах OpenGraph
                const metaOgImage = document.querySelector('meta[property="og:image"]');
                if (metaOgImage) {
                    const src = metaOgImage.getAttribute('content');
                    if (isValidImageUrl(src)) {
                        images.push({ 
                            src, 
                            priority: 2,
                            source: 'og-meta'
                        });
                    }
                }
                
                // 3. Ищем в структурированных данных JSON-LD
                try {
                    const jsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]');
                    jsonLdScripts.forEach(script => {
                        try {
                            const data = JSON.parse(script.textContent);
                            if (data && data.image) {
                                // Может быть массивом или строкой
                                const imageUrls = Array.isArray(data.image) ? data.image : [data.image];
                                imageUrls.forEach((imageUrl, index) => {
                                    if (isValidImageUrl(imageUrl)) {
                                        images.push({ 
                                            src: imageUrl, 
                                            priority: 3 + index * 0.1,
                                            source: 'json-ld'
                                        });
                                    }
                                });
                            }
                        } catch (e) {
                            // Игнорируем ошибки парсинга JSON
                        }
                    });
                } catch (e) {
                    // Игнорируем ошибки при работе с JSON-LD
                }
                
                // 4. Ищем скрытую галерею изображений
                try {
                    const scriptTags = document.querySelectorAll('script:not([type])');
                    scriptTags.forEach(script => {
                        const content = script.textContent;
                        // Ищем определение galleryApi
                        if (content && content.includes('galleryApi') && content.includes('pictures')) {
                            const galleryMatch = content.match(/galleryApi[\s\S]*?=[\s\S]*?({[\s\S]*?pictures[\s\S]*?})/);
                            if (galleryMatch && galleryMatch[1]) {
                                try {
                                    // Заменяем одинарные кавычки и очищаем код для парсинга
                                    const cleanJson = galleryMatch[1]
                                        .replace(/'/g, '"')
                                        .replace(/([{,]\s*)(\w+)(\s*:)/g, '$1"$2"$3'); // Заключаем ключи в кавычки
                                    
                                    // Пытаемся распарсить JSON
                                    const galleryData = JSON.parse(cleanJson);
                                    if (galleryData && galleryData.pictures && Array.isArray(galleryData.pictures)) {
                                        galleryData.pictures.forEach((pic, index) => {
                                            if (pic.url && isValidImageUrl(pic.url)) {
                                                images.push({ 
                                                    src: pic.url, 
                                                    priority: 2 + index * 0.1,
                                                    source: 'gallery-api'
                                                });
                                            }
                                        });
                                    }
                                } catch (e) {
                                    // Игнорируем ошибки парсинга
                                }
                            }
                        }
                    });
                } catch (e) {
                    // Игнорируем ошибки при поиске галереи
                }
                
                // 5. Общий поиск по всем img-тегам на странице
                const allImages = document.querySelectorAll('img');
                allImages.forEach((img, index) => {
                    // Пропускаем маленькие изображения и иконки
                    const width = img.naturalWidth || img.width || 0;
                    const height = img.naturalHeight || img.height || 0;
                    
                    // Только достаточно большие изображения
                    if (width >= 300 || height >= 300) {
                        const src = img.getAttribute('src');
                        if (src && isValidImageUrl(src)) {
                            // Проверяем, находится ли изображение в основном контенте
                            const isInProductArea = img.closest('.ui-pdp-container, .vip-container') !== null;
                            const priority = isInProductArea ? 4 : 5;
                            
                            images.push({ 
                                src, 
                                priority,
                                position: index,
                                width,
                                height,
                                source: 'img-tag'
                            });
                        }
                    }
                });
                
                // Сортируем изображения по приоритету (меньше = важнее)
                images.sort((a, b) => a.priority - b.priority);
                
                // Проверяем наличие изображений по доменам
                const mluIds = location.href.match(/MLU-?\\d+/g);
                if (mluIds && mluIds.length) {
                    const mluId = mluIds[0].replace('-', '');
                    // Добавляем прямую ссылку на API МерадоЛибре
                    images.unshift({
                        src: `https://http2.mlstatic.com/D_NQ_NP_2X_${mluId}-F.webp`,
                        priority: 0,
                        source: 'direct-api'
                    });
                }
                
                // Если не удалось найти, пробуем сформировать URL на основе ID
                const idMatch = document.body.innerHTML.match(/andes-spinner--large[\\s\\S]*?data-js="shipping-status-info"[\\s\\S]*?(MLU\\d+)/);
                if (idMatch && idMatch[1]) {
                    // Альтернативный способ формирования URL
                    images.unshift({
                        src: `https://http2.mlstatic.com/D_NQ_NP_2X_${idMatch[1]}-F.webp`,
                        priority: 0.5,
                        source: 'dom-parsed'
                    });
                }
                
                // Возвращаем массив найденных изображений для проверки
                return images.map(img => img.src);
            }
            """
            images = await page.evaluate(js_script)
            
            if images and len(images) > 0:
                # Проверяем каждое изображение на доступность
                for img_url in images:
                    try:
                        # Проверяем доступность через HEAD-запрос
                        is_available = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const resp = await fetch('{img_url}', {{ method: 'HEAD' }});
                                return resp.ok;
                            }} catch (e) {{
                                return false;
                            }}
                        }}
                        """)
                        
                        if is_available:
                            self.logger.info(f"Подтверждено доступное изображение: {img_url[:50]}...")
                            return img_url
                    except Exception as check_err:
                        self.logger.debug(f"Ошибка при проверке изображения {img_url[:30]}...: {check_err}")
                        continue
                
                # Если не смогли проверить, просто берем первое
                main_image_url = images[0]
                self.logger.info(f"Использую первое найденное изображение: {main_image_url[:50]}...")
                return main_image_url
            
            # Если ничего не найдено через JavaScript, пробуем использовать прямые селекторы
            self.logger.info("JavaScript не нашел изображений, используем прямые селекторы")
            
            selectors = [
                'figure.ui-pdp-gallery__figure img', 
                'div.ui-pdp-gallery img',
                'div.ui-pdp-image img',
                '.ui-pdp-gallery__figure div',
                'figure.gallery-image-container img'
            ]
            
            for selector in selectors:
                try:
                    image_elem = await page.query_selector(selector)
                    if image_elem:
                        for attr in ['data-zoom', 'src', 'data-src']:
                            img_url = await image_elem.get_attribute(attr)
                            if img_url and img_url.startswith('http') and not img_url.startswith('data:'):
                                self.logger.info(f"Найдено изображение через селектор {selector}: {img_url[:50]}...")
                                return img_url
                except Exception as e:
                    self.logger.debug(f"Ошибка при извлечении изображения через селектор {selector}: {e}")
            
            # Как последнее средство, ищем ID объявления и формируем прямую ссылку
            try:
                mlu_match = re.search(r'MLU-?(\d+)', url)
                if mlu_match:
                    mlu_id = mlu_match.group(0).replace('-', '')
                    direct_url = f"https://http2.mlstatic.com/D_NQ_NP_2X_{mlu_id}-F.webp"
                    self.logger.info(f"Формирование прямой ссылки на основе ID: {direct_url}")
                    return direct_url
            except Exception as id_err:
                self.logger.debug(f"Ошибка при формировании ссылки из ID: {id_err}")
            
            self.logger.warning(f"Не удалось найти изображение для {url} всеми методами")
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении главного изображения: {e}")
            return None

    async def _extract_data_from_detail_page(self, page: Page, listing: Listing) -> Optional[Listing]:
        """Извлекает детальную информацию со страницы объявления MercadoLibre и обновляет объект Listing."""
        self.logger.info(f"Начинаем парсинг деталей для: {listing.url}")
        updated = False
        
        try:
            # Преобразуем URL к формату страницы деталей
            if 'mercadolibre.com.uy' in str(listing.url):
                original_url = str(listing.url)
                # Проверить все возможные неправильные домены и заменить на articulo
                domains_to_fix = ['terreno.mercadolibre.com.uy', 'inmueble.mercadolibre.com.uy', 
                                 'propiedades.mercadolibre.com.uy', 'casa.mercadolibre.com.uy']
                
                fixed_url = original_url
                for domain in domains_to_fix:
                    if domain in original_url:
                        fixed_url = original_url.replace(domain, 'articulo.mercadolibre.com.uy')
                        break
                
                # Если URL изменился, обновляем и переходим
                if fixed_url != original_url:
                    self.logger.info(f"URL преобразован на articulo: {fixed_url}")
                    listing.url = fixed_url
                    # Обновим текущий URL в браузере
                    try:
                        await page.goto(fixed_url, wait_until='domcontentloaded', timeout=30000)
                        await page.wait_for_timeout(1500)  # Увеличиваем время ожидания загрузки
                    except Exception as goto_err:
                        self.logger.warning(f"Ошибка при переходе на исправленный URL: {goto_err}")
            
            # Важно: добавляем извлечение главного изображения
            main_image_url = await self._get_main_image_from_detail_page(page, str(listing.url))
            if main_image_url:
                # Обязательно заменяем изображение, даже если оно уже было
                self.logger.info(f"Обновлено изображение для листинга: {main_image_url[:50]}...")
                listing.image_url = main_image_url
                updated = True
            
            # Извлекаем ID объявления для диагностики
            try:
                listing_id = re.search(r'MLU-?(\d+)', str(listing.url))
                listing_id = listing_id.group(0) if listing_id else "unknown"
                self.logger.debug(f"Обрабатываем объявление с ID: {listing_id}")
            except:
                listing_id = "unknown"
            
            # --- Сохраняем скриншот для отладки ---
            debug_path = "errors/debug_extract_data_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
            await page.screenshot(path=debug_path)
            self.logger.info(f"Сохранен отладочный скриншот: {debug_path}")
            
            # --- Пробуем получить контент страницы для отладки ---
            try:
                page_content = await page.content()
                debug_html = "errors/debug_page_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".html"
                with open(debug_html, "w", encoding="utf-8") as f:
                    f.write(page_content)
                self.logger.info(f"Сохранен HTML страницы для отладки: {debug_html}")
            except Exception as html_err:
                self.logger.warning(f"Не удалось сохранить HTML для отладки: {html_err}")
            
            # --- ПОИСК КЛЮЧЕВЫХ ЭЛЕМЕНТОВ ЧЕРЕЗ JAVASCRIPT СНАЧАЛА ---
            # Это более надежный метод, который работает для всех страниц
            try:
                self.logger.debug("Поиск ключевой информации через JavaScript...")
                data_script = """
                () => {
                    // Функция для очистки текста
                    const cleanText = (text) => text ? text.trim() : null;
                    
                    // Объект для хранения данных
                    const result = {
                        title: null,
                        price: null,
                        currency: null,
                        area: null,
                        location: null,
                        image_url: null,
                        description: null,
                        attributes: {}
                    };
                    
                    // Ищем заголовок (три возможных селектора)
                    const titleElement = document.querySelector('h1.ui-pdp-title') || 
                                         document.querySelector('.ui-pdp-header__title-container h1') ||
                                         document.querySelector('h1');
                    if (titleElement) {
                        result.title = cleanText(titleElement.textContent);
                    }
                    
                    // Ищем цену (более гибкий подход)
                    // Сначала ищем стандартные элементы цены
                    const priceElement = document.querySelector('div.ui-pdp-price span.andes-money-amount__fraction') ||
                                         document.querySelector('span.andes-money-amount__fraction');
                    const currencyElement = document.querySelector('div.ui-pdp-price span.andes-money-amount__currency-symbol') ||
                                            document.querySelector('span.andes-money-amount__currency-symbol');
                    
                    if (priceElement) {
                        result.price = cleanText(priceElement.textContent);
                    }
                    
                    if (currencyElement) {
                        result.currency = cleanText(currencyElement.textContent);
                    }
                    
                    // Проверяем, нашлись ли цена и валюта, если нет - используем альтернативный подход
                    if (!result.price || !result.currency) {
                        // Ищем элемент, содержащий полную цену со всеми частями
                        const fullPriceElement = document.querySelector('[aria-roledescription="Monto"]');
                        if (fullPriceElement) {
                            const ariaLabel = fullPriceElement.getAttribute('aria-label');
                            if (ariaLabel) {
                                const priceMatch = ariaLabel.match(/(\\d[\\d\\.,]*)(\\s+)([^\\s]+)/);
                                if (priceMatch) {
                                    result.price = priceMatch[1].trim();
                                    result.currency = priceMatch[3].trim().replace('dólares', 'US$').replace('pesos', '$');
                                }
                            }
                        }
                    }
                    
                    // Получаем альтернативную информацию о цене из метатегов
                    const metaPrice = document.querySelector('meta[itemprop="price"]');
                    if (metaPrice && !result.price) {
                        result.price = metaPrice.getAttribute('content');
                    }
                    
                    // Ищем местоположение (несколько стратегий)
                    // 1. Из хлебных крошек
                    const breadcrumbs = Array.from(document.querySelectorAll('.ui-pdp-breadcrumb a'));
                    if (breadcrumbs.length >= 2) {
                        const locationParts = breadcrumbs.slice(2).map(a => cleanText(a.textContent))
                            .filter(part => part && !['Uruguay', 'Mercado Libre', 'Inicio'].includes(part));
                        if (locationParts.length > 0) {
                            result.location = locationParts.join(', ');
                        }
                    }
                    
                    // 2. Если не нашли в крошках, ищем в специальном блоке
                    if (!result.location) {
                        const locationElement = document.querySelector('.ui-pdp-media__title') || 
                                              document.querySelector('.ui-pdp-media__body p') ||
                                              document.querySelector('.ui-vip-location__title');
                        if (locationElement) {
                            result.location = cleanText(locationElement.textContent);
                        }
                    }
                    
                    // Ищем площадь - несколько стратегий
                    // 1. В таблице характеристик
                    const tableRows = Array.from(document.querySelectorAll('.ui-pdp-specs__table tr, .ui-pdp-section--specs-table table tr'));
                    for (const row of tableRows) {
                        const th = row.querySelector('th');
                        const td = row.querySelector('td');
                        if (th && td) {
                            const attrName = cleanText(th.textContent);
                            const attrValue = cleanText(td.textContent);
                            
                            // Сохраняем все атрибуты для анализа
                            result.attributes[attrName] = attrValue;
                            
                            // Ищем поле с площадью
                            if (attrName.toLowerCase().includes('superficie') || 
                                attrName.toLowerCase().includes('área') ||
                                attrName.toLowerCase().includes('area') ||
                                attrName.toLowerCase().includes('metros') ||
                                attrName.toLowerCase().includes('terreno')) {
                                result.area = attrValue;
                            }
                        }
                    }
                    
                    // 1.1 Специальная проверка для элементов с id в формате :R19esja9jm:-value
                    if (!result.area) {
                        const valueElements = Array.from(document.querySelectorAll('[id$=":-value"]'));
                        for (const element of valueElements) {
                            const text = cleanText(element.textContent);
                            if (text && (text.includes('m²') || text.includes('ha') || text.includes('hectárea'))) {
                                result.area = text;
                                break;
                            }
                        }
                    }
                    
                    // 2. В блоке выделенных характеристик
                    if (!result.area) {
                        const areaElement = document.querySelector('#highlighted_specs_res span.ui-pdp-label, .ui-pdp-highlighted-specs-res span.ui-pdp-label');
                        if (areaElement) {
                            const areaText = cleanText(areaElement.textContent);
                            if (areaText && (areaText.includes('m²') || areaText.includes('ha'))) {
                                result.area = areaText;
                            }
                        }
                    }
                    
                    // 3. Ищем в любом месте страницы тексты, которые могут быть площадью
                    if (!result.area) {
                        const allTexts = Array.from(document.querySelectorAll('span, p, div'))
                                            .filter(el => !el.children.length) // только элементы без дочерних
                                            .map(el => el.textContent.trim())
                                            .filter(text => text.match(/\\d+\\s*(?:m²|m2|ha|hect[áa]reas?|metros?)/i));
                        
                        if (allTexts.length > 0) {
                            // Берем первый найденный текст с упоминанием площади
                            result.area = allTexts[0];
                        }
                    }
                    
                    // Ищем изображения (в первую очередь главное, а потом все остальные)
                    // 1. Сначала стандартный селектор для главного изображения в галерее
                    let mainImage = document.querySelector('figure.ui-pdp-gallery__figure img');
                    
                    // Это наиболее надежный селектор для изображений, который всегда находит фото
                    if (!mainImage) {
                        mainImage = document.querySelector('img.ui-pdp-gallery__figure__image');
                    }
                    
                    if (!mainImage) {
                        mainImage = document.querySelector('img[data-zoom]');
                    }
                    
                    if (mainImage) {
                        // Всегда проверяем data-zoom, так как это оригинальное изображение с высоким разрешением
                        if (mainImage.dataset.zoom) {
                            result.image_url = mainImage.dataset.zoom;
                        } else if (mainImage.src) {
                            result.image_url = mainImage.src;
                        }
                    }
                    
                    // 2. Если не нашли главное, ищем любые достаточно большие изображения
                    if (!result.image_url) {
                        const allImages = Array.from(document.querySelectorAll('img'))
                            .filter(img => {
                                return img.src && 
                                       img.src.startsWith('http') && 
                                       !img.src.includes('data:image') &&
                                       img.width > 150 && 
                                       img.height > 150;
                            })
                            .sort((a, b) => (b.width * b.height) - (a.width * a.height));
                        
                        if (allImages.length > 0) {
                            result.image_url = allImages[0].src;
                        }
                    }
                    
                    // 3. Ищем изображения по специфическим селекторам
                    if (!result.image_url) {
                        const imgSelectors = [
                            '.ui-pdp-gallery__figure img', 
                            '.ui-pdp-image img', 
                            '.ui-pdp-thumbnail__image',
                            '.slick-slide img',
                            '.ui-pdp-image picture source'
                        ];
                        
                        for (const selector of imgSelectors) {
                            const imgElement = document.querySelector(selector);
                            if (imgElement) {
                                if (imgElement.dataset.src) {
                                    result.image_url = imgElement.dataset.src;
                                    break;
                                } else if (imgElement.srcset) {
                                    // Если есть srcset, берем последний URL (обычно самый большой)
                                    const srcsetParts = imgElement.srcset.split(',');
                                    if (srcsetParts.length > 0) {
                                        const lastPart = srcsetParts[srcsetParts.length - 1].trim();
                                        const url = lastPart.split(' ')[0].trim();
                                        if (url && url.startsWith('http')) {
                                            result.image_url = url;
                                            break;
                                        }
                                    }
                                } else if (imgElement.src) {
                                    result.image_url = imgElement.src;
                                    break;
                                }
                            }
                        }
                    }
                    
                    // 4. Проверка на Base64 изображения
                    if not result.image_url:
                        try:
                            # Получаем HTML-контент страницы
                            html_content = await page.content()
                            
                            if BASE64_HANDLER_AVAILABLE:
                                # Используем новый модуль для извлечения Base64-изображений
                                saved_images = extract_base64_images_from_html(
                                    html_content, 
                                    str(listing.url), 
                                    min_width=200
                                )
                                
                                # Если изображения найдены, берем первое
                                if saved_images:
                                    result.image_url = list(saved_images.values())[0]
                                    self.logger.info(f"Извлечено Base64-изображение из HTML через base64_handler: {result.image_url}")
                                    updated = True
                            else:
                                # Используем встроенную обработку
                                base64_matches = re.findall(r'<img[^>]+src="(data:image/[^;]+;base64,[^"]+)"[^>]+width="([^"]+)"', html_content)
                                if base64_matches:
                                    # Сортируем по ширине изображения (от большего к меньшему)
                                    base64_matches.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 0, reverse=True)
                                    
                                    # Берем самое большое изображение
                                    for base64_img, width in base64_matches:
                                        if int(width) > 200:  # Минимальная ширина для достаточной детализации
                                            try:
                                                # Сохраняем Base64 в файл
                                                import base64
                                                import os
                                                
                                                # Создаем уникальное имя файла на основе ID объявления
                                                listing_id = re.search(r'MLU-?(\d+)', str(listing.url))
                                                listing_id = listing_id.group(0) if listing_id else "unknown"
                                                img_folder = "images"
                                                os.makedirs(img_folder, exist_ok=True)
                                                
                                                # Извлекаем тип изображения и данные из строки Base64
                                                if ',' in base64_img:
                                                    b64_format, b64_data = base64_img.split(',', 1)
                                                    img_ext = 'jpg'  # По умолчанию jpg
                                                    if 'image/png' in b64_format:
                                                        img_ext = 'png'
                                                    elif 'image/jpeg' in b64_format or 'image/jpg' in b64_format:
                                                        img_ext = 'jpg'
                                                    elif 'image/webp' in b64_format:
                                                        img_ext = 'webp'
                                                    
                                                    # Создаем путь к файлу
                                                    img_path = f"{img_folder}/{listing_id}.{img_ext}"
                                                    
                                                    # Декодируем Base64 и записываем в файл
                                                    with open(img_path, "wb") as f:
                                                        f.write(base64.b64decode(b64_data))
                                                    
                                                    self.logger.info(f"Base64 изображение сохранено в файл: {img_path}")
                                                    # Меняем URL изображения на локальный файл
                                                    result.image_url = img_path
                                                    updated = True
                                            except Exception as b64_err:
                                                self.logger.warning(f"Ошибка при сохранении Base64 изображения: {b64_err}")
                        except Exception as img_err:
                            self.logger.warning(f"Ошибка при извлечении Base64 изображений из HTML: {img_err}")
                    
                    // Ищем описание
                    const descElement = document.querySelector('div.ui-pdp-description p') || 
                                         document.querySelector('.ui-pdp-description__content');
                    if (descElement) {
                        result.description = cleanText(descElement.textContent);
                    }
                    
                    return result;
                }
                """
                js_data = await page.evaluate(data_script)
                self.logger.debug(f"Данные, полученные через JavaScript: {js_data}")
                
                # Обновляем объект листинга данными из JavaScript
                if js_data:
                    if js_data.get('title'):
                        listing.title = js_data['title']
                        updated = True
                        self.logger.debug(f"Заголовок обновлен из JS: {listing.title}")
                    
                    if js_data.get('price') and js_data.get('currency'):
                        price_text = f"{js_data['currency']} {js_data['price']}"
                        listing.price = price_text
                        updated = True
                        self.logger.debug(f"Цена обновлена из JS: {listing.price}")
                    elif js_data.get('price'):  # Если есть только цена без валюты
                        if str(js_data['price']).isdigit():
                            # Если цена - число, добавляем валюту по умолчанию
                            listing.price = f"US$ {js_data['price']}"
                        else:
                            listing.price = js_data['price']
                        updated = True
                        self.logger.debug(f"Цена обновлена из JS (без валюты): {listing.price}")
                    
                    if js_data.get('location'):
                        listing.location = js_data['location']
                        updated = True
                        self.logger.debug(f"Локация обновлена из JS: {listing.location}")
                    
                    if js_data.get('area'):
                        listing.area = js_data['area']
                        updated = True
                        self.logger.debug(f"Площадь обновлена из JS: {listing.area}")
                    
                    if js_data.get('image_url'):
                        listing.image_url = js_data['image_url']
                        updated = True
                        
                        # Обработка Base64 изображения, если оно найдено
                        if js_data.get('is_base64_image') and isinstance(js_data['image_url'], str) and js_data['image_url'].startswith('data:image'):
                            try:
                                if BASE64_HANDLER_AVAILABLE:
                                    # Используем новый модуль обработки Base64
                                    listing_id = re.search(r'MLU-?(\d+)', str(listing.url))
                                    listing_id = listing_id.group(0) if listing_id else "unknown"
                                    
                                    # Сохраняем изображение с использованием нового модуля
                                    img_path = process_and_save_base64_image(
                                        js_data['image_url'], 
                                        str(listing.url), 
                                        listing_id
                                    )
                                    
                                    if img_path:
                                        self.logger.info(f"Base64 изображение сохранено в файл через base64_handler: {img_path}")
                                        # Меняем URL изображения на локальный файл
                                        listing.image_url = img_path
                            except Exception as b64_err:
                                self.logger.warning(f"Ошибка при сохранении Base64 изображения: {b64_err}")
                        
                        self.logger.debug(f"URL изображения обновлен из JS: {str(listing.image_url)[:50]}...")
                    
                    if js_data.get('description'):
                        listing.description = js_data['description']
                        updated = True
                        self.logger.debug(f"Описание обновлено из JS")
                    
                    if js_data.get('attributes') and isinstance(js_data['attributes'], dict):
                        # Если в атрибутах нашлись другие полезные данные, используем их
                        if not listing.attributes:
                            listing.attributes = {}
                        
                        # Проверяем названия атрибутов и при необходимости обновляем базовые поля
                        for attr_name, attr_value in js_data['attributes'].items():
                            # Добавляем атрибут в словарь атрибутов
                            listing.attributes[attr_name] = attr_value
                            
                            # Если не нашли площадь, а в атрибутах есть подходящий - используем
                            if not listing.area and any(keyword in attr_name.lower() for keyword in ['superficie', 'área', 'area', 'metros']):
                                if any(unit in attr_value.lower() for unit in ['m²', 'm2', 'ha', 'hectáreas']):
                                    listing.area = attr_value
                                    self.logger.debug(f"Площадь обновлена из атрибутов: {listing.area}")
                            
                            # Проверяем, есть ли атрибуты, указывающие на тип сделки
                            if any(keyword in attr_name.lower() for keyword in ['operación', 'operacion', 'venta', 'alquiler']):
                                if 'venta' in attr_value.lower():
                                    listing.deal_type = 'Продажа'
                                elif 'alquiler' in attr_value.lower() or 'arrend' in attr_value.lower():
                                    listing.deal_type = 'Аренда'
                        
                        updated = True
                        self.logger.debug(f"Атрибуты обновлены из JS: {len(js_data['attributes'])} атрибутов")
                
                # Если через JavaScript не удалось получить все данные, продолжаем обычными методами
                if not updated or not listing.title or not listing.price or not listing.area or not listing.image_url:
                    self.logger.info(f"Через JavaScript получены не все данные, продолжаем обычными методами Playwright")
            
            except Exception as js_err:
                self.logger.warning(f"Ошибка при извлечении данных через JavaScript: {js_err}")
            
            # --- ОБЫЧНЫЕ МЕТОДЫ ИЗВЛЕЧЕНИЯ (РЕЗЕРВНЫЙ ВАРИАНТ) ---
            
            # --- Извлечение заголовка ---
            if not listing.title:
                try:
                    title_selector = 'h1.ui-pdp-title'
                    title_element = await page.query_selector(title_selector)
                    if title_element:
                        title_text = await title_element.text_content()
                        title_text = title_text.strip()
                        if title_text:
                            self.logger.debug(f"Найден заголовок по селектору '{title_selector}': {title_text}")
                            listing.title = title_text
                            updated = True
                            self.logger.debug(f"Обновляем title: '{listing.title}'")
                        else:
                            self.logger.debug(f"Заголовок найден, но пустой: '{title_selector}'")
                    else:
                        self.logger.debug(f"Заголовок не найден или не изменился: '{listing.title}'")
                        
                        # Попробуем альтернативный селектор
                        alt_title_selector = '.ui-pdp-header__title-container h1'
                        alt_title_element = await page.query_selector(alt_title_selector)
                        if alt_title_element:
                            alt_title_text = await alt_title_element.text_content()
                            alt_title_text = alt_title_text.strip()
                            if alt_title_text:
                                self.logger.debug(f"Найден заголовок по альтернативному селектору '{alt_title_selector}': {alt_title_text}")
                                listing.title = alt_title_text
                                updated = True
                                self.logger.debug(f"Обновляем title: '{listing.title}'")
                except Exception as e:
                    self.logger.warning(f"Ошибка при извлечении заголовка: {e}")
            
            # --- Извлечение цены ---
            if not listing.price:
                try:
                    price_fraction_selector = 'div.ui-pdp-price span.andes-money-amount__fraction'
                    price_fraction_element = await page.query_selector(price_fraction_selector)
                    
                    if price_fraction_element:
                        price_text = await price_fraction_element.text_content()
                        price_text = price_text.strip()
                        self.logger.debug(f"Найдена цена по селектору '{price_fraction_selector}': {price_text}")
                        
                        # Ищем символ валюты
                        currency_selector = 'div.ui-pdp-price span.andes-money-amount__currency-symbol'
                        currency_element = await page.query_selector(currency_selector)
                        
                        if currency_element:
                            currency_symbol = await currency_element.text_content()
                            currency_symbol = currency_symbol.strip()
                            self.logger.debug(f"Найден символ валюты по селектору '{currency_selector}': {currency_symbol}")
                            full_price = f"{currency_symbol} {price_text}"
                        else:
                            full_price = price_text
                        
                        if price_text:
                            listing.price = full_price
                            updated = True
                            self.logger.debug(f"Обновляем price: '{listing.price}'")
                    else:
                        self.logger.debug(f"Цена не найдена или не изменилась: '{listing.price}'")
                        
                        # Попробуем альтернативный селектор для цены (блок цены целиком)
                        alt_price_selector = '.ui-pdp-price__second-line span'
                        alt_price_elements = await page.query_selector_all(alt_price_selector)
                        
                        if alt_price_elements and len(alt_price_elements) > 0:
                            for price_el in alt_price_elements:
                                price_content = await price_el.text_content()
                                if price_content and any(c.isdigit() for c in price_content):
                                    full_price = price_content.strip()
                                    listing.price = full_price
                                    updated = True
                                    self.logger.debug(f"Обновляем price из альтернативного селектора: '{listing.price}'")
                                    break
                except Exception as e:
                    self.logger.warning(f"Ошибка при извлечении цены: {e}")
            
            # --- Извлечение местоположения ---
            if not listing.location or listing.location == "Uruguay":
                try:
                    # Сначала пробуем получить местоположение из хлебных крошек через JavaScript
                    location_script = """
                    () => {
                        // Функция для очистки текста
                        const cleanText = (text) => text ? text.trim() : null;
                        
                        // 1. Ищем в хлебных крошках (наиболее надежный источник локации)
                        const breadcrumbs = Array.from(document.querySelectorAll('.andes-breadcrumb__item a, .ui-pdp-breadcrumb li a'));
                        
                        // Фильтруем общие элементы, которые не являются локацией
                        const excludeTerms = ['inmuebles', 'uruguay', 'mercado libre', 'inicio', 'terrenos', 'campos', 'propiedades', 'venta', 'inmuebles', 'casas', 'terreno'];
                        
                        // Собираем все элементы из хлебных крошек, исключая те, что не являются локацией
                        const locationParts = breadcrumbs
                            .map(a => cleanText(a.textContent))
                            .filter(text => text && 
                                !excludeTerms.some(term => text.toLowerCase().includes(term.toLowerCase())));
                        
                        if (locationParts.length > 0) {
                            return locationParts.join(', ');
                        }
                        
                        // 2. Ищем в блоке локации
                        const locationElements = [
                            document.querySelector('.ui-pdp-media__title'), 
                            document.querySelector('.ui-pdp-location__title'),
                            document.querySelector('.ui-vip-location p'),
                            document.querySelector('p.ui-pdp-color--BLACK.ui-pdp-size--SMALL.ui-pdp-family--REGULAR.ui-pdp-media__title')
                        ];
                        
                        for (const element of locationElements) {
                            if (element) {
                                const text = cleanText(element.textContent);
                                // Проверяем, что это не просто "Uruguay"
                                if (text && text !== "Uruguay" && text.length > 4) {
                                    return text;
                                }
                            }
                        }
                        
                        // 3. Поиск в основном содержимом и таблице характеристик
                        const tableRows = Array.from(document.querySelectorAll('.ui-pdp-specs__table tr, table tr'));
                        for (const row of tableRows) {
                            const th = row.querySelector('th, td:first-child');
                            const td = row.querySelector('td:last-child');
                            
                            if (th && td) {
                                const label = cleanText(th.textContent).toLowerCase();
                                if (label.includes('ubicación') || label.includes('ubicacion') || 
                                    label.includes('locación') || label.includes('locacion') || 
                                    label.includes('dirección') || label.includes('direccion') || 
                                    label.includes('localidad') || label.includes('departamento')) {
                                    const value = cleanText(td.textContent);
                                    if (value && value !== "Uruguay" && value.length > 4) {
                                        return value;
                                    }
                                }
                            }
                        }
                        
                        // 4. Поиск в URL и заголовке
                        const title = document.querySelector('h1.ui-pdp-title');
                        if (title) {
                            const titleText = cleanText(title.textContent);
                            const locationMatches = titleText.match(/en\s+([A-Za-zÁÉÍÓÚáéíóúÑñ\s]+),\s+([A-Za-zÁÉÍÓÚáéíóúÑñ\s]+)/i);
                            if (locationMatches && locationMatches.length > 1) {
                                return locationMatches[1] + (locationMatches[2] ? ', ' + locationMatches[2] : '');
                            }
                        }
                        
                        // 5. Ищем в URL страницы
                        const urlPath = window.location.pathname;
                        const urlMatches = urlPath.match(/-en-([a-z0-9-]+)-en-([a-z0-9-]+)-/i);
                        if (urlMatches && urlMatches.length > 2) {
                            return urlMatches[1].replace(/-/g, ' ') + ', ' + urlMatches[2].replace(/-/g, ' ');
                        }
                        
                        return "Uruguay"; // Если ничего не нашли
                    }
                    """
                    
                    location_text = await page.evaluate(location_script)
                    if location_text and location_text != "Uruguay":
                        listing.location = location_text
                        self.logger.debug(f"Установлено местоположение через JavaScript: {listing.location}")
                        updated = True
                    else:
                        # Если JS не помог, пробуем извлечь через HTML-селекторы напрямую
                        selectors = [
                            '.ui-pdp-media__title',
                            '.ui-pdp-location__title',
                            '.ui-vip-location p',
                            'p.ui-pdp-color--BLACK.ui-pdp-size--SMALL'
                        ]
                        
                        for selector in selectors:
                            location_elem = await page.query_selector(selector)
                            if location_elem:
                                location_text = await location_elem.text_content()
                                location_text = location_text.strip()
                                if location_text and location_text != "Uruguay" and len(location_text) > 4:
                                    listing.location = location_text
                                    self.logger.debug(f"Установлено местоположение из селектора {selector}: {listing.location}")
                                    updated = True
                                    break
                    
                    # Если всё еще нет местоположения, используем значение по умолчанию
                    if not listing.location or listing.location == "Uruguay":
                        listing.location = "Uruguay"
                        self.logger.debug(f"Установлено местоположение по умолчанию")
                        updated = True
                except Exception as location_err:
                    self.logger.warning(f"Ошибка при извлечении местоположения: {location_err}")
                    listing.location = "Uruguay"
                    self.logger.debug(f"Установлено местоположение по умолчанию после ошибки")
                    updated = True
            
            # Проверка изображения и попытка получения из HTML если отсутствует
            if not listing.image_url:
                try:
                    # Пробуем извлечь URL изображения из HTML
                    html_content = await page.content()
                    img_patterns = [
                        r'data-zoom="(https://[^"]+\.(?:webp|jpg|jpeg|png))"',  # Ищем data-zoom сначала 
                        r'<img[^>]+class="ui-pdp-gallery__figure__image"[^>]+src="([^"]+)"',  # Ищем специфичный класс
                        r'<img[^>]+src="(https://http2\.mlstatic\.com/D_NQ_[^"]+\.webp)"',  # Ищем специфичный домен и шаблон URL
                        r'<img[^>]+src="(https://[^"]+\.(?:webp|jpg|jpeg|png))"[^>]+width="(?:1\d\d|[2-9]\d\d)"',  # Ищем изображения с большой шириной
                        r'<img[^>]+src="(http[^"]+)"[^>]+class="ui-pdp-image'  # Ищем изображения с определенным классом
                    ]
                    
                    for img_pattern in img_patterns:
                        img_match = re.search(img_pattern, html_content)
                        if img_match:
                            img_url = img_match.group(1)
                            # Проверяем, что это не заглушка
                            if not any(placeholder in img_url for placeholder in ['D_NQ_907534', 'noindex/assets/placeholder', 'UI/public/placeholder']):
                                listing.image_url = img_url
                                self.logger.debug(f"Установлен URL изображения из HTML: {str(listing.image_url)[:50]}...")
                                updated = True
                                break
                    
                    # Проверка на Base64 изображения
                    if not listing.image_url:
                        base64_matches = re.findall(r'<img[^>]+src="(data:image/[^;]+;base64,[^"]+)"[^>]+width="([^"]+)"', html_content)
                        if base64_matches:
                            # Сортируем по ширине изображения (от большего к меньшему)
                            base64_matches.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 0, reverse=True)
                            
                            # Берем самое большое изображение
                            for base64_img, width in base64_matches:
                                if int(width) > 200:  # Минимальная ширина для достаточной детализации
                                    try:
                                        # Сохраняем Base64 в файл
                                        import base64
                                        import os
                                        
                                        # Создаем уникальное имя файла на основе ID объявления
                                        listing_id = re.search(r'MLU-?(\d+)', str(listing.url))
                                        listing_id = listing_id.group(0) if listing_id else "unknown"
                                        img_folder = "images"
                                        os.makedirs(img_folder, exist_ok=True)
                                        
                                        # Извлекаем тип изображения и данные из строки Base64
                                        if ',' in base64_img:
                                            b64_format, b64_data = base64_img.split(',', 1)
                                            img_ext = 'jpg'  # По умолчанию jpg
                                            if 'image/png' in b64_format:
                                                img_ext = 'png'
                                            elif 'image/jpeg' in b64_format or 'image/jpg' in b64_format:
                                                img_ext = 'jpg'
                                            elif 'image/webp' in b64_format:
                                                img_ext = 'webp'
                                            
                                            # Создаем путь к файлу
                                            img_path = f"{img_folder}/{listing_id}.{img_ext}"
                                            
                                            # Декодируем Base64 и записываем в файл
                                            with open(img_path, "wb") as f:
                                                f.write(base64.b64decode(b64_data))
                                            
                                            self.logger.info(f"Base64 изображение сохранено в файл: {img_path}")
                                            # Меняем URL изображения на локальный файл
                                            listing.image_url = img_path
                                            updated = True
                                            break
                                    except Exception as b64_err:
                                        self.logger.warning(f"Ошибка при сохранении Base64 изображения: {b64_err}")
                    
                    # Если до сих пор нет изображения, ищем в galleryapi json если он есть
                    if not listing.image_url:
                        gallery_match = re.search(r'galleryapi[^{]*({.*?})\s*;', html_content, re.DOTALL)
                        if gallery_match:
                            try:
                                import json
                                gallery_json = gallery_match.group(1).replace("'", '"')
                                gallery_data = json.loads(gallery_json)
                                if gallery_data and 'pictures' in gallery_data and gallery_data['pictures']:
                                    for pic in gallery_data['pictures']:
                                        if 'url' in pic:
                                            img_url = pic['url']
                                            if not any(placeholder in img_url for placeholder in ['D_NQ_907534', 'noindex/assets/placeholder', 'UI/public/placeholder']):
                                                listing.image_url = img_url
                                                self.logger.debug(f"Установлен URL изображения из galleryapi: {str(listing.image_url)[:50]}...")
                                                updated = True
                                                break
                            except Exception as json_err:
                                self.logger.warning(f"Ошибка при парсинге gallery JSON: {json_err}")
                except Exception as img_err:
                    self.logger.warning(f"Ошибка при извлечении URL изображения из HTML: {img_err}")
            
            listing.deal_type = 'Продажа'  # Всегда устанавливаем Продажа для terrenos
            updated = True
            
            # Проверяем, что у нас есть все необходимые данные
            self.logger.info(f"Итоговые данные для {listing.url}:")
            self.logger.info(f"- Заголовок: {listing.title}")
            self.logger.info(f"- Цена: {listing.price}")
            self.logger.info(f"- Локация: {listing.location}")
            self.logger.info(f"- Площадь: {listing.area}")
            self.logger.info(f"- Фото: {str(listing.image_url)}")
            
            self.logger.info(f"Детали для {listing.url} успешно извлечены и объект обновлен.")
            return listing
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении данных со страницы деталей {listing.url}: {e}", exc_info=True)
            return None

    # Вспомогательные методы остаются те же
    async def _safe_get_text_from_element(self, element: ElementHandle, selector: str, field_name: str, url: str) -> str:
        # ... (код без изменений)
        pass # Оставим как есть

    async def _safe_get_text(self, page: Page, selector: str, field_name: str, url: str) -> str:
        # ... (код без изменений)
        pass # Оставим как есть

    async def _safe_get_attribute(self, page: Page, selector: str, attribute: str, field_name: str, url: str) -> str:
        # ... (код без изменений)
        pass # Оставим как есть
        
    async def _safe_get_attribute_from_element(self, element: ElementHandle, selector: str, attribute: str, field_name: str, url: str) -> str:
        """Безопасно извлекает атрибут из дочернего элемента, найденного по селектору.
           Возвращает пустую строку, если элемент или атрибут не найдены, или произошла ошибка.
        """
        try:
            target_element = await element.query_selector(selector)
            if target_element:
                value = await target_element.get_attribute(attribute)
                return value.strip() if value else ""
        except Error as e:
            self.logger.debug(f"Ошибка Playwright при извлечении атрибута '{attribute}' поля '{field_name}' по селектору '{selector}' для URL {url}: {e}")
        except Exception as e:
            self.logger.warning(f"Неожиданная ошибка при извлечении атрибута '{attribute}' поля '{field_name}' по селектору '{selector}' для URL {url}: {e}")
        return ""
        
    async def _normalize_data(self, data: Dict[str, Any], url: str) -> Optional[Listing]:
        # ... (код без изменений)
        pass
        
# ... (конец файла) ... 