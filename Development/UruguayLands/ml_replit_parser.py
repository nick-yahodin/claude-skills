#!/usr/bin/env python3
"""
Оптимизированный парсер MercadoLibre для деплоя на Replit.
Упрощенная версия без лишних зависимостей.
"""

import asyncio
import logging
import re
import json
import os
import sys
import base64
import random
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from urllib.parse import urljoin
import aiohttp

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("MLParser")

# Константы
DEFAULT_IMAGE_DIR = "images"
BASE_URL = "https://listado.mercadolibre.com.uy/inmuebles/terrenos/venta/"
SEARCH_URL_TEMPLATE = BASE_URL + "/_Desde_{offset}"

# Шаблоны доступа к изображениям через API
IMAGE_API_TEMPLATES = [
    # Основной формат (2X - высокое разрешение)
    "https://http2.mlstatic.com/D_NQ_NP_2X_{item_id}-F.webp",
    # Второй формат (нумерованный)
    "https://http2.mlstatic.com/D_NQ_NP_2X_{item_id}-{number}.webp",
    # Стандартное разрешение
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-F.webp",
    # Стандартное разрешение с номером 
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-{number}.webp",
    # Альтернативные форматы (старые)
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-O.webp",
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-V.webp",
]

# Селекторы для страницы списка
LIST_SELECTORS = {
    'container': 'ol.ui-search-layout',
    'item': 'li.ui-search-layout__item',
    'url': 'div.ui-search-result__content a.ui-search-link',
    'title': 'h2.ui-search-item__title',
    'price': 'span.price-tag-fraction',
    'currency': 'span.price-tag-symbol',
    'address': 'span.ui-search-item__location',
    'area': 'ul.ui-search-card-attributes li.ui-search-card-attributes__attribute',
    'image': 'img.ui-search-result-image__element',
}

# Селекторы для страницы деталей
DETAIL_SELECTORS = {
    'title': 'h1.ui-pdp-title',
    'price_fraction': 'span.andes-money-amount__fraction',
    'price_currency': 'span.andes-money-amount__currency-symbol',
    'description': 'div.ui-pdp-description__content',
    'main_image': 'figure.ui-pdp-gallery__figure img',
    'area': 'div.ui-pdp-specs__table tr:contains("Superficie")',
    'attributes_table': 'div.ui-pdp-specs__table',
    'location': 'div.ui-pdp-media__title',
}

# Кэш URL изображений
IMAGE_URL_CACHE = {}

# Механизм кэширования URL изображений
def cache_image_url(listing_id: str, image_url: str):
    """Кэширует URL изображения для объявления"""
    IMAGE_URL_CACHE[listing_id] = {
        'url': image_url,
        'timestamp': datetime.now().timestamp()
    }
    
    # Сохраняем кэш в файл
    try:
        with open('image_url_cache.json', 'w') as f:
            json.dump(IMAGE_URL_CACHE, f)
    except Exception as e:
        logger.error(f"Ошибка при сохранении кэша изображений: {e}")

def get_cached_image_url(listing_id: str) -> Optional[str]:
    """Получает URL изображения из кэша, если он есть и не устарел"""
    if listing_id in IMAGE_URL_CACHE:
        cache_entry = IMAGE_URL_CACHE[listing_id]
        # Проверяем, не устарела ли запись (7 дней)
        if datetime.now().timestamp() - cache_entry['timestamp'] < 7 * 24 * 60 * 60:
            return cache_entry['url']
    return None

# Загрузка кэша при старте
def load_image_url_cache():
    """Загружает кэш URL изображений из файла"""
    global IMAGE_URL_CACHE
    try:
        if os.path.exists('image_url_cache.json'):
            with open('image_url_cache.json', 'r') as f:
                IMAGE_URL_CACHE = json.load(f)
            logger.info(f"Загружен кэш изображений: {len(IMAGE_URL_CACHE)} записей")
    except Exception as e:
        logger.error(f"Ошибка при загрузке кэша изображений: {e}")
        IMAGE_URL_CACHE = {}

# Проверка качества изображения
async def check_image_quality(session: aiohttp.ClientSession, image_url: str) -> bool:
    """Проверяет, не является ли изображение заглушкой"""
    try:
        async with session.get(image_url, timeout=10) as response:
            if response.status != 200:
                return False
                
            # Получаем размер изображения
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) < 5000:
                logger.warning(f"Изображение слишком маленькое: {content_length} байт")
                return False
                
            # Проверяем тип контента
            content_type = response.headers.get('Content-Type', '')
            if 'image/' not in content_type:
                logger.warning(f"Неверный тип контента: {content_type}")
                return False
                
            # Проверяем заглушки по URL
            if any(x in image_url for x in ['mercadolibre.com/homes', 'placeholder', 'org-img']):
                logger.warning(f"URL содержит признаки заглушки: {image_url}")
                return False
                
            # Для более детальной проверки можно скачать часть изображения
            # и проанализировать его метаданные
            
            return True
    except Exception as e:
        logger.error(f"Ошибка при проверке качества изображения {image_url}: {e}")
        return False

async def generate_image_variants(item_id: str) -> List[str]:
    """
    Генерирует все возможные варианты URL изображений для указанного ID.
    
    Args:
        item_id: ID товара (MLU-XXXXXXX)
        
    Returns:
        List[str]: Список всех возможных URL изображений
    """
    # Нормализуем ID (удаляем дефис, если есть)
    normalized_id = item_id.replace("-", "")
    pure_id = re.sub(r'^MLU', '', normalized_id)
    
    variants = []
    
    # Генерируем URL из шаблонов - оптимизированный порядок
    # Начинаем с наиболее вероятных шаблонов
    for template in IMAGE_API_TEMPLATES:
        if "{number}" in template:
            # Для шаблонов с номерами добавляем сначала без номера (наиболее вероятно)
            variants.append(template.format(item_id=normalized_id, number=""))
            # Затем добавляем варианты с номерами от 2 до 5 (чаще всего используются)
            for i in range(2, 6):
                variants.append(template.format(item_id=normalized_id, number=i))
        else:
            # Для шаблонов без номеров просто форматируем
            variants.append(template.format(item_id=normalized_id))
    
    # Добавляем дополнительные варианты с датами в ID (оптимизированный список)
    date_patterns = ["", "637399", "941697"]
    for pattern in date_patterns:
        variants.append(f"https://http2.mlstatic.com/D_NQ_NP_2X_{pattern}{pure_id}-F.webp")
    
    return variants

async def check_image_url(session: aiohttp.ClientSession, url: str) -> bool:
    """Проверяет доступность изображения по URL."""
    try:
        async with session.head(url, allow_redirects=True, timeout=10) as response:
            if response.status == 200:
                content_type = response.headers.get('Content-Type', '')
                if 'image/' in content_type:
                    return True
    except Exception as e:
        logger.debug(f"Ошибка при проверке URL {url}: {e}")
    
    return False

async def save_image_from_url(session: aiohttp.ClientSession, url: str, save_path: str) -> bool:
    """Скачивает и сохраняет изображение."""
    try:
        async with session.get(url, timeout=20) as response:
            if response.status == 200:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(await response.read())
                logger.info(f"Изображение сохранено: {save_path}")
                return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении изображения {url}: {e}")
    
    return False

async def get_image_for_listing(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """
    Получает изображение для указанного URL листинга.
    Оптимизированная версия с кэшированием и проверкой качества.
    
    Args:
        session: Сессия aiohttp
        url: URL страницы товара
        
    Returns:
        Optional[str]: URL изображения или None
    """
    # Извлекаем ID товара из URL
    id_match = re.search(r'MLU-?(\d+)', url)
    if not id_match:
        logger.error(f"Не удалось извлечь ID товара из URL: {url}")
        return None
    
    item_id = id_match.group(0)
    logger.info(f"Получение изображения для {item_id}")
    
    # Проверяем кэш
    cached_url = get_cached_image_url(item_id)
    if cached_url:
        logger.info(f"Найдено изображение в кэше для {item_id}: {cached_url}")
        # Проверяем, что изображение все еще доступно
        if await check_image_url(session, cached_url):
            return cached_url
        else:
            logger.warning(f"Кэшированное изображение недоступно: {cached_url}")
    
    # 1. Пробуем прямые URL по шаблонам
    variants = await generate_image_variants(item_id)
    logger.info(f"Сгенерировано {len(variants)} вариантов URL для {item_id}")
    
    for i, img_url in enumerate(variants):
        if i % 5 == 0:
            logger.debug(f"Проверка вариантов {i+1}-{min(i+5, len(variants))} из {len(variants)}")
        
        is_available = await check_image_url(session, img_url)
        if is_available:
            # Проверяем качество изображения
            if await check_image_quality(session, img_url):
                logger.info(f"Найдено качественное изображение для {item_id}: {img_url}")
                # Сохраняем в кэш
                cache_image_url(item_id, img_url)
                return img_url
            else:
                logger.warning(f"Изображение не прошло проверку качества: {img_url}")
    
    # 2. Если ничего не нашли, пробуем извлечь из HTML
    logger.info(f"Не удалось найти изображение по шаблонам для {item_id}. Пытаемся извлечь из HTML...")
    
    try:
        async with session.get(url, timeout=20) as response:
            if response.status == 200:
                html = await response.text()
                
                # Ищем ID изображения в HTML (основные шаблоны)
                patterns = [
                    r'"picture_id":"([^"]+)"',
                    r'"image_id":"([^"]+)"',
                    r'data-zoom="https://http2\.mlstatic\.com/D_NQ_NP_\d*_?([^"\.]+)',
                    r'https://http2\.mlstatic\.com/D_NQ_NP_\d*_?([^"\.]+)\.webp'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html)
                    if matches:
                        image_id = matches[0]
                        logger.info(f"Извлечен ID изображения из страницы: {image_id}")
                        
                        # Формируем и проверяем URL на основе найденного ID
                        img_urls = [
                            f"https://http2.mlstatic.com/D_NQ_NP_2X_{image_id}.webp",
                            f"https://http2.mlstatic.com/D_NQ_NP_{image_id}.webp"
                        ]
                        
                        for img_url in img_urls:
                            if await check_image_url(session, img_url):
                                if await check_image_quality(session, img_url):
                                    # Сохраняем в кэш
                                    cache_image_url(item_id, img_url)
                                    return img_url
                
                # 3. Если не нашли ID, ищем готовые URL в HTML
                img_url_patterns = [
                    r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.webp)"',
                    r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.jpg)"',
                    r'content="(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.(webp|jpg))"'
                ]
                
                for pattern in img_url_patterns:
                    img_matches = re.findall(pattern, html)
                    if img_matches:
                        for img_match in img_matches:
                            img_url = img_match[0] if isinstance(img_match, tuple) else img_match
                            if img_url.startswith('http') and 'http2.mlstatic.com' in img_url:
                                # Проверяем, что это не заглушка
                                if await check_image_quality(session, img_url):
                                    # Сохраняем в кэш
                                    cache_image_url(item_id, img_url)
                                    return img_url
    except Exception as e:
        logger.error(f"Ошибка при извлечении изображения из HTML: {e}")
    
    logger.warning(f"Не удалось найти изображение для {item_id}")
    return None

async def get_listing(url: str) -> Dict[str, Any]:
    """
    Получает данные объявления по URL.
    
    Args:
        url: URL объявления на MercadoLibre
        
    Returns:
        Dict[str, Any]: Данные объявления
    """
    listing_data = {
        "source": "mercadolibre",
        "url": url,
        "timestamp": datetime.now().isoformat()
    }
    
    # Валидация URL
    if not re.search(r'mercadolibre\.com', url):
        return {"error": "Invalid URL, not a MercadoLibre link"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=30) as response:
                if response.status != 200:
                    return {"error": f"Failed to fetch listing page, status: {response.status}"}
                
                html = await response.text()
                
                # Извлекаем данные с помощью регулярных выражений
                # Заголовок
                title_match = re.search(r'<h1[^>]*class="ui-pdp-title"[^>]*>(.*?)</h1>', html)
                if title_match:
                    listing_data["title"] = title_match.group(1).strip()
                
                # Цена
                price_matches = re.findall(r'<span[^>]*class="andes-money-amount__currency-symbol"[^>]*>(.*?)</span>.*?<span[^>]*class="andes-money-amount__fraction"[^>]*>(.*?)</span>', html, re.DOTALL)
                if price_matches:
                    currency, amount = price_matches[0]
                    listing_data["price"] = f"{currency.strip()} {amount.strip()}"
                
                # Описание
                desc_match = re.search(r'<div[^>]*class="ui-pdp-description__content"[^>]*>(.*?)</div>', html, re.DOTALL)
                if desc_match:
                    description = desc_match.group(1).strip()
                    # Очищаем HTML-теги
                    description = re.sub(r'<[^>]+>', ' ', description)
                    description = re.sub(r'\s+', ' ', description).strip()
                    listing_data["description"] = description
                
                # Местоположение
                location_match = re.search(r'<p[^>]*class="ui-pdp-media__title"[^>]*>(.*?)</p>', html)
                if location_match:
                    listing_data["location"] = location_match.group(1).strip()
                
                # Атрибуты (включая площадь)
                area_match = re.search(r'Superficie.*?</td>.*?<td[^>]*>(.*?)</td>', html, re.DOTALL)
                if area_match:
                    listing_data["area"] = area_match.group(1).strip()
                    
                # Ищем площадь в другом формате, если не нашли
                if "area" not in listing_data:
                    area_alt_match = re.search(r'(\d+(?:,\d+)?)\s*m²', html)
                    if area_alt_match:
                        listing_data["area"] = f"{area_alt_match.group(1)} m²"
                
                # Получаем изображение
                image_url = await get_image_for_listing(session, url)
                if image_url:
                    listing_data["image_url"] = image_url
                
                return listing_data
                
        except Exception as e:
            logger.error(f"Error while processing listing {url}: {e}")
            return {"error": str(e), "url": url}

async def test_random_listings(num_listings: int = 5):
    """
    Тестирует систему на случайных объявлениях.
    
    Args:
        num_listings: Количество случайных объявлений для теста
    """
    # Загружаем кэш URL изображений
    load_image_url_cache()
    
    # Создаем сессию
    async with aiohttp.ClientSession() as session:
        # Получаем список объявлений с первой страницы MercadoLibre
        try:
            search_url = BASE_URL
            logger.info(f"Получение списка объявлений с {search_url}")
            
            async with session.get(search_url, timeout=30) as response:
                if response.status != 200:
                    logger.error(f"Ошибка при получении списка объявлений: {response.status}")
                    return
                
                html = await response.text()
                
                # Сохраняем HTML для диагностики
                with open("search_page.html", "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info("HTML сохранен в search_page.html для анализа")
                
                # Более простые шаблоны для поиска URL
                url_patterns = [
                    r'href="(https://[^"]*articulo\.mercadolibre\.com\.uy/MLU-[^"]*)"',
                    r'href="(https://[^"]*casa\.mercadolibre\.com\.uy/MLU-[^"]*)"',
                    r'href="(https://[^"]*inmueble\.mercadolibre\.com\.uy/MLU-[^"]*)"',
                    r'href="(https://[^"]*/MLU-[^"]*)"'
                ]
                
                all_urls = []
                for pattern in url_patterns:
                    urls = re.findall(pattern, html)
                    all_urls.extend(urls)
                    logger.info(f"Найдено {len(urls)} URL по шаблону {pattern}")
                
                if not all_urls:
                    # Последняя попытка - ищем все ссылки содержащие MLU-
                    urls = re.findall(r'href="([^"]*MLU-[^"]*)"', html)
                    all_urls.extend([url for url in urls if url.startswith('http')])
                    logger.info(f"Найдено {len(urls)} URL по общему шаблону MLU-")
                
                if not all_urls:
                    logger.error("Не найдены URL объявлений на странице")
                    
                    # Если не можем найти URL, используем тестовые URL
                    test_sample_urls = [
                        "https://casa.mercadolibre.com.uy/MLU-2335827293-terreno-punta-colorada-_JM",
                        "https://inmueble.mercadolibre.com.uy/MLU-2365622831-terrenos-en-la-floresta-cuotas-en-pesos-_JM",
                        "https://casa.mercadolibre.com.uy/MLU-2364721119-maldonado-terreno-en-cerro-del-burro-_JM"
                    ]
                    logger.info("Используем заранее определенные тестовые URL")
                    all_urls = test_sample_urls
                
                # Получаем только уникальные URL
                unique_urls = list(set(all_urls))
                logger.info(f"Найдено {len(unique_urls)} уникальных URL объявлений")
                
                # Ограничиваем количество URL для теста
                test_urls = random.sample(unique_urls, min(num_listings, len(unique_urls)))
                
                # Обрабатываем каждое объявление
                results = []
                for i, url in enumerate(test_urls):
                    logger.info(f"Обработка объявления {i+1}/{len(test_urls)}: {url}")
                    
                    # Получаем данные объявления
                    listing_data = await get_listing(url)
                    results.append(listing_data)
                    
                    # Небольшая задержка между запросами
                    await asyncio.sleep(2)
                
                # Сохраняем результаты
                os.makedirs("test_results", exist_ok=True)
                result_file = f"test_results/ml_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                
                with open(result_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                
                logger.info(f"Результаты сохранены в {result_file}")
                
                return results
                
        except Exception as e:
            logger.error(f"Ошибка при тестировании системы: {e}")
            return []

# Добавляем функцию parse_infocasas для совместимости
async def parse_infocasas(max_pages=2):
    """
    Простая обертка для парсера InfoCasas.
    Обрабатывает объявления с сайта InfoCasas.
    
    Args:
        max_pages: Максимальное количество страниц для парсинга
        
    Returns:
        list: Список данных объявлений
    """
    logger.info(f"Запуск парсера InfoCasas для {max_pages} страниц")
    
    try:
        # Проверяем, доступен ли класс InfoCasasParser
        try:
            from app.parsers.infocasas import InfoCasasParser
            
            # Создаем экземпляр и запускаем
            parser = InfoCasasParser()
            listings = await parser.run(max_pages=max_pages, headless=True)
            
            logger.info(f"InfoCasas: Найдено {len(listings)} объявлений")
            return listings
            
        except ImportError:
            # Если не можем импортировать класс, используем заглушку
            logger.warning("Не удалось импортировать InfoCasasParser. Используем заглушку.")
            
            # Возвращаем пустой список, так как парсер недоступен
            return []
            
    except Exception as e:
        logger.error(f"Ошибка в процессе парсинга InfoCasas: {e}")
        return []

# Модифицируем функцию main для запуска обоих парсеров
async def main():
    """Основная функция приложения"""
    # Загружаем кэш URL изображений
    load_image_url_cache()
    
    # Если указан URL в аргументах командной строки, обрабатываем его
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        url = sys.argv[1]
        logger.info(f"Обработка URL из аргументов: {url}")
        
        listing_data = await get_listing(url)
        print(json.dumps(listing_data, ensure_ascii=False, indent=2))
    else:
        # Иначе запускаем тест случайных объявлений MercadoLibre
        # и пытаемся запустить InfoCasas
        logger.info("Запуск теста случайных объявлений MercadoLibre")
        ml_results = await test_random_listings(3)
        
        # Запускаем парсер InfoCasas
        logger.info("Запуск парсера InfoCasas")
        ic_results = await parse_infocasas(1)
        
        # Вывод результатов MercadoLibre
        if ml_results:
            print("\n=== Результаты тестирования MercadoLibre ===")
            for i, listing in enumerate(ml_results):
                print(f"\n{i+1}. {listing.get('title', 'Заголовок не найден')}")
                print(f"   Цена: {listing.get('price', 'Не указана')}")
                print(f"   Местоположение: {listing.get('location', 'Не указано')}")
                print(f"   Площадь: {listing.get('area', 'Не указана')}")
                print(f"   Изображение: {'Найдено' if 'image_url' in listing else 'Не найдено'}")
                print(f"   URL: {listing.get('url', 'Не указан')}")
        
        # Вывод результатов InfoCasas
        if ic_results:
            print("\n=== Результаты парсинга InfoCasas ===")
            print(f"Найдено {len(ic_results)} объявлений")
            
            # Показываем первые 3 объявления
            for i, listing in enumerate(ic_results[:3]):
                print(f"\n{i+1}. {listing.title}")
                print(f"   Цена: {listing.price}")
                print(f"   Местоположение: {listing.location}")
                print(f"   Площадь: {listing.area}")
                print(f"   URL: {listing.url}")

if __name__ == "__main__":
    asyncio.run(main())