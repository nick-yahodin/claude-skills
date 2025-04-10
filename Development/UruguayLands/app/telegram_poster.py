#!/usr/bin/env python3
"""
Модуль для отправки сообщений об объявлениях в Telegram-канал.
"""

import logging
import os
import re
import tempfile
import base64
from io import BytesIO
from typing import Dict, Any, Optional, List
import sys
from pathlib import Path
import asyncio
import uuid
import aiohttp
import time
import random
from urllib.parse import urlparse, unquote

# Добавляем путь к корню проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent # -> UruguayLands/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

import requests
from PIL import Image, UnidentifiedImageError
from telegram import Bot, InputMediaPhoto, InputFile
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ExtBot # Используем Application для асинхронности

from app.models import Listing
from app.hashtag_generator import generate_hashtags

# Добавляем загрузку .env при прямом запуске
from dotenv import load_dotenv
# Путь к файлу .env относительно текущего файла
DOTENV_PATH = PROJECT_ROOT / 'config' / '.env'
if DOTENV_PATH.exists():
    load_dotenv(dotenv_path=DOTENV_PATH)

from config.settings import TELEGRAM_SETTINGS
try:
    from app.base64_handler import (
        is_base64_image, process_and_save_base64_image, 
        extract_base64_images_from_html, get_image_for_listing
    )
    # Маркер для проверки, доступен ли модуль
    BASE64_HANDLER_AVAILABLE = True
except ImportError:
    # Если модуль не найден, будем использовать встроенную обработку
    BASE64_HANDLER_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "Модуль app.base64_handler не найден полностью. Некоторые функции будут недоступны."
    )

logger = logging.getLogger(__name__)

# --- Настройки --- 
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

# Проверка наличия токена и ID канала
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN не найден в переменных окружения!")
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")
if not CHAT_ID:
    logger.critical("CHAT_ID не найден в переменных окружения!")
    raise ValueError("CHAT_ID не найден в переменных окружения!")

# Инициализация бота асинхронно
# Создаем Application, чтобы получить доступ к асинхронному боту
application = Application.builder().token(BOT_TOKEN).build()
# Получаем экземпляр ExtBot (асинхронный)
async_bot: ExtBot = application.bot

# --- Вспомогательные функции для изображений --- 

async def fetch_image(image_url: str) -> Optional[bytes]:
    """
    Асинхронно загружает изображение по URL.
    
    Args:
        image_url: URL изображения для загрузки
    
    Returns:
        Optional[bytes]: Бинарные данные изображения или None в случае ошибки
    """
    try:
        logger.info(f"[Download Img] Попытка скачивания: {image_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=30) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'image/' in content_type:
                        data = await response.read()
                        logger.info(f"[Download Img] Изображение успешно скачано и проверено: {image_url}")
                        return data
                    else:
                        logger.warning(f"[Download Img] Неверный Content-Type: {content_type} для {image_url}")
                else:
                    logger.warning(f"[Download Img] Ошибка при скачивании {image_url}: статус {response.status}")
    except Exception as e:
        logger.error(f"[Download Img] Ошибка при скачивании {image_url}: {e}")
    
    return None

def is_valid_image_url(image_url_str: str) -> bool:
    """Проверяет, доступен ли URL изображения и является ли он изображением."""
    if not image_url_str or not image_url_str.startswith('http'):
        logger.debug(f"[Check Img URL] Невалидный формат или не http: {image_url_str}")
        return False
    
    # Специальная обработка для URL изображений MercadoLibre
    if 'mlstatic.com' in image_url_str:
        logger.info(f"[Check Img URL] Обнаружен URL MercadoLibre, считаем валидным: {image_url_str}")
        return True
        
    try:
        response = requests.head(image_url_str, timeout=10, allow_redirects=True)
        content_type = response.headers.get('Content-Type', '').lower()
        if response.status_code == 200 and 'image' in content_type:
            logger.debug(f"[Check Img URL] URL является изображением: {image_url_str}")
            return True
        else:
            logger.debug(f"[Check Img URL] URL не является изображением: {image_url_str}, status={response.status_code}, content-type={content_type}")
    except Exception as e:
        logger.warning(f"[Check Img URL] Ошибка при проверке URL изображения {image_url_str}: {e}")
    
    return False

def save_base64_image(base64_str: str) -> Optional[BytesIO]:
    """Декодирует Base64 строку в изображение и возвращает BytesIO."""
    try:
        # Убираем префикс, если он есть
        if ';base64,' in base64_str:
            base64_str = base64_str.split('base64,')[-1]
        
        img_data = base64.b64decode(base64_str)
        
        # Проверяем, что это действительно изображение
        img = Image.open(BytesIO(img_data))
        img.verify()
        logger.info("Изображение Base64 успешно декодировано и проверено.")
        return BytesIO(img_data)
    except (base64.binascii.Error, UnidentifiedImageError, OSError) as e:
        logger.warning(f"Ошибка при обработке Base64 изображения: {e}")
        return None
    except Exception as e:
         logger.error(f"Неизвестная ошибка при обработке Base64: {e}")
         return None

# --- Форматирование сообщения --- 

def format_telegram_message(listing: Dict[str, Any]) -> str:
    """
    Форматирует данные объявления в сообщение для Telegram (HTML) 
    в стиле предоставленного скриншота.
    """
    # Получаем данные, обрабатывая None
    source = listing.get('source', 'Unknown').capitalize()
    location = listing.get('location', 'N/A')
    price = listing.get('price', 'N/A')
    area = listing.get('area', 'N/A')
    deal_type = listing.get('deal_type', 'N/A') 
    utilities = listing.get('utilities', 'None')
    url = listing.get('url', '')
    title = listing.get('title', 'New listing')
    
    # Генерируем хэштеги, если их нет
    if not listing.get('hashtags'):
        from app.hashtag_generator import generate_hashtags
        listing['hashtags'] = generate_hashtags(listing)
    hashtags = listing.get('hashtags', [])
    
    # Нормализуем площадь
    area_text = area
    if area and area != 'N/A':
        area_match_m2 = re.search(r'(\d+[.,]?\d*)\s*(m²|m2|metros|mts)', area, re.IGNORECASE)
        area_match_ha = re.search(r'(\d+[.,]?\d*)\s*(ha|hect[áa]reas?)', area, re.IGNORECASE)
        if area_match_ha:
            area_text = f"{area_match_ha.group(1).replace(',', '.')} hectáreas"
        elif area_match_m2:
            area_text = f"{area_match_m2.group(1).replace(',', '.')} m²"

    # Проверяем и исправляем URL
    cleaned_url = url
    
    # Проверка на корректность URL MercadoLibre
    if 'mercadolibre' in cleaned_url.lower():
        # Формат должен быть https://articulo.mercadolibre.com.uy/MLU-XXXXXXX-...
        if '/listado.' in cleaned_url or '_OrderId_' in cleaned_url or '_Desde_' in cleaned_url or 'terreno.mercadolibre.com.uy' in cleaned_url:
            logger.warning(f"Обнаружен неправильный URL MercadoLibre: {cleaned_url}")
            
            # Ищем ID объявления в URL
            mlu_match = re.search(r'(MLU[-_]\d+)', cleaned_url)
            if mlu_match:
                mlu_id = mlu_match.group(1).replace('_', '-')
                corrected_url = f"https://articulo.mercadolibre.com.uy/{mlu_id}-"
                cleaned_url = corrected_url
                logger.info(f"URL исправлен на: {cleaned_url}")
            else:
                logger.error(f"Не удалось найти ID объявления в URL: {cleaned_url}")
        
        # Проверим, что URL начинается с articulo, а не с terreno
        elif not cleaned_url.startswith('https://articulo.mercadolibre.com.uy/'):
            original_url = cleaned_url
            cleaned_url = cleaned_url.replace('terreno.mercadolibre.com.uy', 'articulo.mercadolibre.com.uy')
            if cleaned_url != original_url:
                logger.info(f"URL преобразован из terreno в articulo: {cleaned_url}")

    # Собираем сообщение в новом формате по скриншоту
    message_lines = [
        f"<b>New listing from {source}</b>",
        f"", # Пустая строка для отступа
        f"📍 Location: {location}",
        f"💲 Price: {price}",
        f"📐 Area: {area_text}",
        f"🏠 Type: {listing.get('property_type', 'Not specified')}",
        f"🤝 Deal: {deal_type}",
        f"🔌 Utilities: {utilities}",
        f"", # Пустая строка для отступа
        f"🔗 <a href='{cleaned_url}'>View listing link</a>",
        f"", # Пустая строка для отступа
        f"{' '.join(hashtags)}"
    ]
    
    # Убираем пустые строки и удаляем линии с None или N/A значениями
    message = "\n".join(line for line in message_lines if line and "Not specified" not in line and "N/A" not in line)

    # <<< Добавляем проверку на пустое сообщение >>>
    assert message and message.strip(), "Formatted message is empty!"

    return message[:4090] + '...' if len(message) > 4096 else message

# --- Альтернативная функция отправки через requests ---
def send_telegram_direct(message: str, chat_id: str = CHAT_ID, token: str = BOT_TOKEN) -> bool:
    """
    Отправляет сообщение в Telegram напрямую через HTTP API без использования python-telegram-bot.
    
    Args:
        message: Текст сообщения с HTML-форматированием
        chat_id: ID чата (по умолчанию из .env)
        token: Токен бота (по умолчанию из .env)
    
    Returns:
        bool: True если сообщение отправлено успешно, False в случае ошибки
    """
    logger.info("Отправка сообщения напрямую через requests API")
    
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True  # Отключаем предпросмотр ссылок
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            logger.info(f"Сообщение успешно отправлено через requests API (status: {response.status_code})")
            return True
        else:
            logger.error(f"Ошибка отправки через requests API: {response.status_code}, {response.text}")
            return False
    except Exception as e:
        logger.error(f"Исключение при отправке через requests API: {e}")
        return False

# Псевдоним для обратной совместимости
# send_telegram_sync = send_telegram_direct

# --- Синхронная отправка через requests (для теста) --- 
def send_telegram_sync(listing: Dict[str, Any]) -> bool:
    """Отправляет текстовое сообщение через requests напрямую в Telegram API."""
    logger.info(f"[SYNC SEND] Подготовка к синхронной отправке: {listing.get('id') or listing.get('url')}")
    
    # Форматируем базовое сообщение
    formatted_message = format_telegram_message(listing)
    
    # Добавляем UUID для уникальности
    formatted_message += f"\n\n[SYNC-UUID: {uuid.uuid4()}]"

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': formatted_message[:4096], # Ограничение длины
        'parse_mode': 'HTML'
    }
    
    logger.debug(f"[SYNC SEND] Запрос к API: {api_url}")
    
    try:
        response = requests.post(api_url, json=payload, timeout=20) # Увеличим таймаут
        response_json = response.json() # Пытаемся получить JSON ответ
        
        logger.debug(f"[SYNC SEND] Статус ответа: {response.status_code}")
        logger.debug(f"[SYNC SEND] Тело ответа: {response_json}")
        
        if response.status_code == 200 and response_json.get('ok') is True:
            logger.info(f"[SYNC SEND] Сообщение успешно отправлено через requests: {listing.get('id') or listing.get('url')}")
            return True
        else:
            logger.error(f"[SYNC SEND] Ошибка при отправке через requests. Статус: {response.status_code}, Ответ: {response_json}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"[SYNC SEND] Ошибка requests: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"[SYNC SEND] Неизвестная ошибка: {e}", exc_info=True)
        return False

# --- Основная функция отправки --- 

async def post_to_telegram(listing: Dict[str, Any]) -> bool:
    """
    Асинхронно отправляет сообщение о недвижимости в Telegram.
    
    Args:
        listing: Словарь с данными объявления (title, price, location, url, source, etc.)
        
    Returns:
        bool: True если сообщение успешно отправлено, False в противном случае
    """
    retry_count = 3  # Количество повторных попыток при ошибке
    logger.info(f"Подготовка к отправке в Telegram: {listing.get('url')}")
    
    # Логика проверки и фиксации URL MercadoLibre при необходимости
    url = listing.get('url', '')
    if url and 'mercadolibre.com.uy' in url:
        domains_to_fix = ['terreno.mercadolibre.com.uy', 'inmueble.mercadolibre.com.uy', 
                          'casa.mercadolibre.com.uy', 'campo.mercadolibre.com.uy', 
                          'apartamento.mercadolibre.com.uy', 'propiedades.mercadolibre.com.uy']
        
        cleaned_url = url
        for domain in domains_to_fix:
            if domain in url:
                # Преобразуем URL к articulo.mercadolibre.com.uy для устранения редиректов
                cleaned_url = url.replace(domain, 'articulo.mercadolibre.com.uy')
                logger.debug(f"URL MercadoLibre исправлен: {url} -> {cleaned_url}")
                break
    else:
        cleaned_url = url
    
    # Локализация текста
    source = listing.get('source', 'MercadoLibre')
    if source == "mercadolibre":
        source = "Mercadolibre"
    
    # Получение основных данных для сообщения
    title = listing.get('title', 'Not specified')
    price = listing.get('price', 'Not specified')
    location = listing.get('location', 'N/A')
    area = listing.get('area', 'Not specified')
    
    # Дополнительные поля с дефолтными значениями
    deal_type = listing.get('deal_type', 'Sale')
    utilities = listing.get('utilities', 'None')
    
    # Если есть deal_type, локализуем его
    if deal_type == "Venta":
        deal_type = "Продажа"
    elif deal_type == "Alquiler":
        deal_type = "Аренда"
    
    # Формирование текста площади с учетом формата
    area_text = area if area else "Not specified"
    
    # Оформление хэштегов для улучшения распознаваемости
    hashtags = []
    # Базовые хэштеги
    hashtags.append("#InmueblesUY")  # Основной хэштег для недвижимости в Уругвае
    
    # Хэштеги по типу объявления
    if 'property_type' in listing:
        prop_type = listing.get('property_type', '').lower()
        if 'terreno' in prop_type or 'lote' in prop_type:
            hashtags.append("#TerrenosUY")
        elif 'casa' in prop_type:
            hashtags.append("#CasasUY")
        elif 'apart' in prop_type or 'apto' in prop_type:
            hashtags.append("#ApartamentosUY")
        elif 'campo' in prop_type or 'rural' in prop_type:
            hashtags.append("#CamposUY")
        elif 'comercial' in prop_type or 'negocio' in prop_type:
            hashtags.append("#ComercialesUY")
        
    # Хэштеги по площади
    if area:
        area_str = str(area).lower().replace('.', '')
        area_num = None
        try:
            # Пытаемся извлечь число из строки площади
            area_match = re.search(r'(\d+)', area_str)
            if area_match:
                area_num = int(area_match.group(1))
        except Exception:
            pass
            
        if area_num is not None:
            if 'm²' in area_str:
                if area_num < 100:
                    hashtags.append("#MenosDe100m")
                elif area_num < 500:
                    hashtags.append("#MenosDe500m")
                elif area_num < 1000:
                    hashtags.append("#MenosDe1000m")
                elif area_num < 10000:
                    hashtags.append("#MenosDe1Ha")
                else:
                    hashtags.append("#MasDe1Ha")
            elif 'ha' in area_str:
                hashtags.append("#MasDe1Ha")
    
    # Хэштеги по местоположению
    if location:
        location_lower = location.lower()
        if 'montevideo' in location_lower:
            hashtags.append("#Montevideo")
        elif 'maldonado' in location_lower or 'punta del este' in location_lower:
            hashtags.append("#Maldonado")
        elif 'colonia' in location_lower:
            hashtags.append("#Colonia")
        elif 'rocha' in location_lower:
            hashtags.append("#Rocha")
        elif 'canelones' in location_lower:
            hashtags.append("#Canelones")
        else:
            hashtags.append("#Uruguay")
            
        # Специфические местоположения
        if 'punta del este' in location_lower:
            hashtags.append("#PuntaDelEste")
        elif 'la barra' in location_lower:
            hashtags.append("#LaBarra")
        elif 'jose ignacio' in location_lower or 'josé ignacio' in location_lower:
            hashtags.append("#JoseIgnacio")
        
    # Хэштеги по цене
    if price:
        price_lower = price.lower()
        if 'US$' in price or 'USD' in price or 'U$S' in price:
            # Доллары
            price_match = re.search(r'(\d+)', price)
            if price_match:
                try:
                    price_num = int(price_match.group(1).replace('.', '').replace(',', ''))
                    if price_num < 50000:
                        hashtags.append("#MenosDe50K")
                    elif price_num < 100000:
                        hashtags.append("#MenosDe100K")
                    elif price_num < 200000:
                        hashtags.append("#MenosDe200K")
                    elif price_num < 500000:
                        hashtags.append("#MenosDe500K")
                    elif price_num < 1000000:
                        hashtags.append("#MenosDe1M")
                    else:
                        hashtags.append("#MasDe1M")
                except (ValueError, IndexError):
                    pass
                    
    # Хэштеги по типу сделки
    if deal_type == "Продажа":
        hashtags.append("#Вода")
        hashtags.append("#УДороги")
    elif deal_type == "Аренда":
        hashtags.append("#Аренда")
    
    # Хэштеги по особенностям
    if location and any(x in location.lower() for x in ['playa', 'costa', 'mar', 'oceano', 'beach']):
        hashtags.append("#CercaDelMar")
        
    if utilities:
        utilities_lower = utilities.lower()
        if 'agua' in utilities_lower or 'water' in utilities_lower:
            hashtags.append("#ConAgua")
        if 'luz' in utilities_lower or 'electric' in utilities_lower:
            hashtags.append("#ConLuz")
        if 'gas' in utilities_lower:
            hashtags.append("#ConGas")
        if 'internet' in utilities_lower or 'wifi' in utilities_lower:
            hashtags.append("#ConInternet")
        
    # Хэштег с использованием определенных ключевых слов из описания
    if 'description' in listing and listing['description']:
        desc = listing['description'].lower()
        if 'bosque' in desc or 'forest' in desc:
            hashtags.append("#ConBosque")
        if 'lago' in desc or 'lake' in desc:
            hashtags.append("#ConLago")
        if 'río' in desc or 'rio' in desc or 'river' in desc:
            hashtags.append("#ConRio")
        if 'vista' in desc and ('mar' in desc or 'sea' in desc or 'ocean' in desc):
            hashtags.append("#VistaAlMar")
        if any(x in desc for x in ['ubicación desconocida', 'ubicacion desconocida']):
            hashtags.append("#UbicacionDesconocida")
    
    # Определяем, отправлять ли с изображением или только текст
    image_content = None
    has_image = False
    image_url = listing.get('image_url')
    
    if image_url:
        logger.info(f"Изображение найдено в объекте: {image_url}")
        
        # Проверка, является ли изображение base64-строкой
        if isinstance(image_url, str) and BASE64_HANDLER_AVAILABLE and is_base64_image(image_url):
            logger.info(f"Обнаружено base64-изображение")
            
            # Попытка сохранить base64-изображение во временный файл
            try:
                # Сохраняем base64 в файл
                item_id = None
                if url:
                    id_match = re.search(r'MLU-?(\d+)', url)
                    if id_match:
                        item_id = id_match.group(0)
                
                img_path = process_and_save_base64_image(image_url, url, item_id)
                if img_path:
                    logger.info(f"base64-изображение сохранено в файл: {img_path}")
                    # Читаем файл для отправки
                    with open(img_path, 'rb') as f:
                        image_content = f.read()
                        has_image = True
            except Exception as e:
                logger.error(f"Ошибка при обработке base64-изображения: {e}")
        
        # Если это файловый путь, а не URL
        elif isinstance(image_url, str) and (image_url.startswith('/') or os.path.exists(image_url)):
            try:
                logger.info(f"Изображение является локальным файлом: {image_url}")
                with open(image_url, 'rb') as f:
                    image_content = f.read()
                    has_image = True
            except Exception as e:
                logger.error(f"Ошибка при чтении локального файла изображения {image_url}: {e}")
        
        # Обычный URL изображения
        elif isinstance(image_url, str) and is_valid_image_url(image_url):
            logger.info(f"Скачиваем изображение с URL: {image_url}")
            try:
                image_content = await fetch_image(image_url)
                has_image = image_content is not None
            except Exception as e:
                logger.error(f"Ошибка при скачивании изображения по URL {image_url}: {e}")
    
    # Если изображение не найдено или не удалось скачать, пробуем получить его через API
    if not has_image and BASE64_HANDLER_AVAILABLE and url:
        logger.info("Изображение не найдено в объекте, пробуем получить через API")
        try:
            img_path = await get_image_for_listing(url)
            if img_path:
                logger.info(f"Изображение получено через API: {img_path}")
                with open(img_path, 'rb') as f:
                    image_content = f.read()
                    has_image = True
                    # Обновляем image_url в объекте listing для последующего использования
                    listing['image_url'] = img_path
        except Exception as e:
            logger.error(f"Ошибка при получении изображения через API: {e}")
    
    # Если всё ещё нет изображения, используем заглушку
    if not has_image:
        logger.warning("Изображение не найдено или не удалось скачать, пробуем использовать заглушку")
        # Проверяем наличие дефолтного изображения
        default_img_paths = [
            'assets/default_property.jpg',
            'UruguayLands/assets/default_property.jpg',
            '/Users/nick/Development/UruguayLands/assets/default_property.jpg'
        ]
        
        for path in default_img_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'rb') as f:
                        image_content = f.read()
                        has_image = True
                        logger.info(f"Используем дефолтное изображение: {path}")
                        break
                except Exception as e:
                    logger.error(f"Ошибка при чтении дефолтного изображения {path}: {e}")
    
    # Собираем сообщение в новом формате по скриншоту
    message_lines = [
        f"<b>New listing from {source}</b>",
        f"", # Пустая строка для отступа
        f"📍 Location: {location}",
        f"💲 Price: {price}",
        f"📐 Area: {area_text}",
        f"🏠 Type: {listing.get('property_type', 'Not specified')}",
        f"🤝 Deal: {deal_type}",
        f"🔌 Utilities: {utilities}",
        f"", # Пустая строка для отступа
        f"🔗 <a href='{cleaned_url}'>View listing link</a>",
        f"", # Пустая строка для отступа
        f"{' '.join(hashtags)}"
    ]

    # Объединяем строки в одно сообщение
    message_text = "\n".join(message_lines)
    
    # Отправляем сообщение в Telegram
    for attempt in range(retry_count):
        try:
            # Получаем настройки из конфигурации
            bot_token = TELEGRAM_SETTINGS.get('BOT_TOKEN')
            chat_id = TELEGRAM_SETTINGS.get('CHAT_ID')
            
            if not bot_token or not chat_id:
                logger.error("Не найдены настройки Telegram в конфигурации (BOT_TOKEN или CHAT_ID)")
                return False
            
            # Подготавливаем URL для запроса
            telegram_api_url = f"https://api.telegram.org/bot{bot_token}/"
            
            # Добавляем параметры, общие для всех типов сообщений
            params = {
                'chat_id': chat_id,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,  # Отключаем превью ссылок
            }
            
            # Используем aiohttp для асинхронных запросов
            async with aiohttp.ClientSession() as session:
                if has_image and image_content:
                    logger.info(f"Отправка объявления с изображением: {title}")
                    # Отправляем фото с текстом
                    form_data = aiohttp.FormData()
                    form_data.add_field('chat_id', str(chat_id))
                    form_data.add_field('caption', message_text)
                    form_data.add_field('parse_mode', 'HTML')
                    form_data.add_field('disable_web_page_preview', 'true')
                    
                    # Добавляем изображение как содержимое
                    form_data.add_field('photo', image_content, 
                                       filename='property.jpg',
                                       content_type='image/jpeg')
                    
                    # Отправляем запрос
                    async with session.post(telegram_api_url + 'sendPhoto', data=form_data) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get('ok'):
                                logger.info(f"Объявление успешно отправлено в Telegram: {url}")
                                return True
                            else:
                                error_desc = result.get('description', 'Unknown error')
                                logger.error(f"Ошибка при отправке в Telegram: {error_desc}")
                        else:
                            logger.error(f"Ошибка HTTP при отправке в Telegram: {response.status}")
                            # Если ошибка связана с изображением, пробуем отправить только текст
                            if response.status == 400:
                                logger.warning("Попытка отправить сообщение без изображения")
                                has_image = False
                                continue
                else:
                    logger.info(f"Отправка объявления без изображения: {title}")
                    # Отправляем только текст
                    params['text'] = message_text
                    async with session.post(telegram_api_url + 'sendMessage', params=params) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get('ok'):
                                logger.info(f"Объявление успешно отправлено в Telegram: {url}")
                                return True
                            else:
                                error_desc = result.get('description', 'Unknown error')
                                logger.error(f"Ошибка при отправке в Telegram: {error_desc}")
                        else:
                            logger.error(f"Ошибка HTTP при отправке в Telegram: {response.status}")
        
        except Exception as e:
            logger.error(f"Ошибка при отправке в Telegram (попытка {attempt+1}/{retry_count}): {e}")
        
        # Если не последняя попытка, ждем перед повторной попыткой
        if attempt < retry_count - 1:
            delay = (attempt + 1) * 2  # Увеличиваем задержку с каждой попыткой
            logger.info(f"Ожидание {delay} сек перед повторной попыткой...")
            await asyncio.sleep(delay)
    
    logger.error(f"Не удалось отправить объявление в Telegram после {retry_count} попыток")
    return False

# --- Тестовая функция (для локальной отладки) --- 
async def test_telegram_poster():
    logger.info("Запуск тестовой отправки в Telegram...")
    test_listing = {
        "source": "TestSite",
        "title": "Тестовый Участок с Домом и Видом на Море",
        "url": "https://example.com/test",
        "price": "USD 150.000",
        "location": "Тестовый Город, Тестовый Регион",
        "area": "5 hectáreas",
        "image_url": "https://via.placeholder.com/600x400.png?text=Test+Image", # Валидный URL для теста
        # "image_url": None, # Тест без изображения
        # "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", # Тест base64
        "description": "Отличный тестовый участок для проверки постинга. Есть электричество, вода и деревья.",
        "id": "TEST-123",
        "hashtags": generate_hashtags({"source": "TestSite", "title": "Тестовый Участок", "location": "Тестовый Регион"}) # Генерируем тестовые хэштеги
    }
    
    # Тестирование нового прямого метода отправки
    logger.info("=== ТЕСТ 1: Отправка через ПРЯМОЙ API (requests) ===")
    simple_message = f"""
<b>Тестовое сообщение - DIRECT API</b>

📌 <b>{test_listing['title']}</b>
💲 Цена: {test_listing['price']}
📍 Местоположение: {test_listing['location']}

🔗 <a href="{test_listing['url']}">Посмотреть объявление</a>

#Test #DirectAPI
    """
    
    direct_success = send_telegram_direct(simple_message)
    if direct_success:
        logger.info("✅ Прямой метод отправки УСПЕШЕН")
    else:
        logger.error("❌ Прямой метод отправки ПРОВАЛИЛСЯ")
    
    # Небольшая пауза между отправками
    await asyncio.sleep(2)
    
    # Тестирование стандартного метода через python-telegram-bot
    logger.info("=== ТЕСТ 2: Отправка через python-telegram-bot ===")
    try:
        await post_to_telegram(test_listing)
        logger.info("✅ Отправка через python-telegram-bot УСПЕШНА")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке через python-telegram-bot: {e}", exc_info=True)

async def send_telegram_message_async(listing: Dict[str, Any], bot_token=None, chat_id=None, retry_count=3) -> bool:
    """
    Асинхронно отправляет сообщение о недвижимости в Telegram с использованием aiohttp.
    Возвращает True, если отправка успешна, False в противном случае.
    """
    import aiohttp
    import os
    from urllib.parse import quote
    import json
    import time
    import random
    
    # Настройка логгера для модуля
    logger = logging.getLogger(__name__)
    
    # Получаем токен и ID чата (из переданных параметров или из среды)
    bot_token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN') or "7682404666:AAFbehrAAZ3MC-DyLk4QKtm7Y4rN1EbGh3A"
    chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID') or "-4156782637"
    
    # Формируем сообщение
    message_html = format_telegram_message(listing)
    logger.info(f"Подготовка к отправке в Telegram: {listing.get('url')}")
    
    # Определяем, отправлять ли с изображением или только текст
    has_image = False
    img_url = listing.get('image_url')
    downloaded_img_path = None  # Путь к скачанному изображению, если потребуется
    
    if img_url:
        # Проверяем, является ли изображение локальным файлом (для Base64-изображений)
        if os.path.isfile(img_url):
            logger.debug(f"Обнаружено локальное изображение: {img_url}")
            has_image = True
            downloaded_img_path = img_url
        else:
            # Проверяем валидность URL изображения
            try:
                logger.debug(f"Проверка URL изображения: {img_url}")
                async with aiohttp.ClientSession() as session:
                    async with session.head(img_url, allow_redirects=True) as resp:
                        if resp.status == 200:
                            content_type = resp.headers.get('Content-Type', '')
                            if content_type.startswith('image/'):
                                has_image = True
                                logger.debug(f"[Check Img URL] Валиден: {img_url} (Status: {resp.status}, Type: {content_type})")
                            else:
                                logger.warning(f"[Check Img URL] Неверный тип контента: {img_url} (Type: {content_type})")
                        else:
                            logger.warning(f"[Check Img URL] Недоступен: {img_url} (Status: {resp.status})")
            except Exception as e:
                logger.warning(f"[Check Img URL] Ошибка: {img_url} ({str(e)})")
    
    # Если URL изображения валиден, пытаемся скачать его для отправки в Telegram
    if has_image and not downloaded_img_path:
        try:
            logger.info(f"[Download Img] Попытка скачивания: {img_url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(img_url, allow_redirects=True) as resp:
                    if resp.status == 200:
                        logger.debug(f"[Download Img] Запрос успешен (Status: {resp.status}) для {img_url}")
                        content_type = resp.headers.get('Content-Type', 'image/jpeg')
                        ext = content_type.split('/')[-1].split(';')[0].replace('jpeg', 'jpg')
                        if not ext:
                            ext = 'jpg'  # По умолчанию jpg
                        
                        # Создаем временный файл для изображения
                        tmp_dir = 'tmp_images'
                        os.makedirs(tmp_dir, exist_ok=True)
                        image_data = await resp.read()
                        
                        # Проверяем, что изображение не повреждено и имеет достаточный размер
                        if len(image_data) > 1024:  # Минимум 1 КБ
                            filename = f"{tmp_dir}/listing_image_{int(time.time())}_{random.randint(1000, 9999)}.{ext}"
                            with open(filename, 'wb') as f:
                                f.write(image_data)
                            downloaded_img_path = filename
                            logger.info(f"[Download Img] Изображение успешно скачано и проверено: {img_url}")
                        else:
                            logger.warning(f"[Download Img] Изображение слишком маленькое: {len(image_data)} байт")
                            has_image = False
                    else:
                        logger.warning(f"[Download Img] Ошибка скачивания (Status: {resp.status}): {img_url}")
                        has_image = False
        except Exception as e:
            logger.warning(f"[Download Img] Ошибка: {img_url} ({str(e)})")
            has_image = False

if __name__ == "__main__":
    # Конфигурация логгера при прямом запуске
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    # Запуск тестовой функции при прямом вызове скрипта
    asyncio.run(test_telegram_poster()) 