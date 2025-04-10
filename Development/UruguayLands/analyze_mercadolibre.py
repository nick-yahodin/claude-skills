#!/usr/bin/env python3
"""
Скрипт для анализа структуры страницы MercadoLibre с объявлениями о продаже земельных участков.
Выполняет детальный анализ HTML-структуры, извлекает селекторы и сохраняет примеры для отладки.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import re

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ml_analyzer")

# Добавляем корневую директорию проекта в sys.path
import sys
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from playwright.async_api import async_playwright, Page, Browser
except ImportError:
    logger.error("Playwright не установлен. Установите через: pip install playwright")
    logger.info("После установки выполните: playwright install")
    sys.exit(1)

# Создаем папку для результатов анализа
RESULTS_DIR = PROJECT_ROOT / "analysis_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Конфигурация
TARGET_URL = "https://listado.mercadolibre.com.uy/inmuebles/terrenos/venta/"
HEADLESS = True  # Запускать браузер в фоновом режиме
SAVE_ARTIFACTS = True  # Сохранять HTML, скриншоты и результаты анализа

async def save_html(page: Page, filename: str):
    """Сохраняет HTML-код страницы в файл."""
    html_content = await page.content()
    file_path = RESULTS_DIR / f"{filename}.html"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"HTML-код сохранен в {file_path}")
    return file_path

async def save_screenshot(page: Page, filename: str, full_page: bool = True):
    """Делает и сохраняет скриншот страницы."""
    file_path = RESULTS_DIR / f"{filename}.png"
    await page.screenshot(path=file_path, full_page=full_page)
    logger.info(f"Скриншот сохранен в {file_path}")
    return file_path

async def save_element_screenshot(page: Page, selector: str, filename: str):
    """Делает и сохраняет скриншот конкретного элемента."""
    element = await page.query_selector(selector)
    if element:
        file_path = RESULTS_DIR / f"{filename}.png"
        await element.screenshot(path=file_path)
        logger.info(f"Скриншот элемента '{selector}' сохранен в {file_path}")
        return file_path
    else:
        logger.warning(f"Элемент '{selector}' не найден для скриншота")
        return None

async def save_json(data: Any, filename: str):
    """Сохраняет данные в JSON-файл."""
    file_path = RESULTS_DIR / f"{filename}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"JSON-данные сохранены в {file_path}")
    return file_path

async def analyze_tag_attributes(page: Page, selector: str, tag_type: str = None):
    """Анализирует атрибуты тега/элемента для определения потенциальных селекторов."""
    data = {}
    elements = await page.query_selector_all(selector)
    
    if not elements:
        logger.warning(f"Не найдено элементов по селектору: {selector}")
        return data
    
    logger.info(f"Найдено {len(elements)} элементов по селектору: {selector}")
    
    if tag_type:
        # Если указан тип тега, фильтруем только эти элементы
        filtered_elements = []
        for element in elements:
            tag_name = await page.evaluate("el => el.tagName.toLowerCase()", element)
            if tag_name == tag_type.lower():
                filtered_elements.append(element)
        elements = filtered_elements
        logger.info(f"После фильтрации по тегу '{tag_type}' осталось {len(elements)} элементов")
    
    if not elements:
        return data
    
    # Анализируем первые 5 элементов (или меньше, если найдено меньше)
    for i, element in enumerate(elements[:5]):
        tag_name = await page.evaluate("el => el.tagName.toLowerCase()", element)
        attributes = await page.evaluate("el => Object.entries(el.attributes).map(([_, attr]) => [attr.name, attr.value])", element)
        classes = await page.evaluate("el => el.className", element)
        id_attr = await page.evaluate("el => el.id", element)
        html = await page.evaluate("el => el.outerHTML", element)
        text = await page.evaluate("el => el.textContent", element)
        
        element_data = {
            "tag": tag_name,
            "attributes": dict(attributes),
            "classes": classes.split() if isinstance(classes, str) else [],
            "id": id_attr,
            "text_sample": text.strip()[:100] if text else "",
            "html_sample": html[:500] if html else ""
        }
        
        data[f"element_{i+1}"] = element_data
    
    return data

async def extract_selectors_from_card(page: Page, card_selector: str):
    """Извлекает различные селекторы из карточки товара."""
    cards = await page.query_selector_all(card_selector)
    if not cards:
        logger.warning(f"Не найдено карточек по селектору: {card_selector}")
        return None
    
    # Берем первую карточку для анализа
    card = cards[0]
    card_html = await page.evaluate("el => el.outerHTML", card)
    
    # Сохраняем HTML первой карточки
    card_html_path = RESULTS_DIR / "first_card.html"
    with open(card_html_path, "w", encoding="utf-8") as f:
        f.write(card_html)
    logger.info(f"HTML первой карточки сохранен в {card_html_path}")
    
    # Извлекаем основные элементы карточки
    selectors = {}
    
    # Поиск URL (ссылки)
    link_selectors = ["a", "a.ui-search-link", "a.poly-component__title", "h3 a"]
    for link_selector in link_selectors:
        link = await card.query_selector(link_selector)
        if link:
            href = await link.get_attribute("href")
            if href and href.startswith("http"):
                selectors["url"] = {
                    "selector": link_selector,
                    "sample": href
                }
                break
    
    # Поиск заголовка
    title_selectors = ["h2", "h3", "span.poly-component__headline", "h3.poly-component__title-wrapper a", "a.poly-component__title"]
    for title_selector in title_selectors:
        title_el = await card.query_selector(title_selector)
        if title_el:
            title_text = await title_el.text_content()
            if title_text and title_text.strip():
                selectors["title"] = {
                    "selector": title_selector,
                    "sample": title_text.strip()
                }
                break
    
    # Поиск цены
    price_selectors = [".andes-money-amount__fraction", ".poly-component__price .andes-money-amount__fraction", "div.poly-price__current .andes-money-amount__fraction"]
    for price_selector in price_selectors:
        price_el = await card.query_selector(price_selector)
        if price_el:
            price_text = await price_el.text_content()
            if price_text and price_text.strip():
                selectors["price"] = {
                    "selector": price_selector,
                    "sample": price_text.strip()
                }
                break
    
    # Поиск валюты
    currency_selectors = [".andes-money-amount__currency-symbol", ".poly-component__price .andes-money-amount__currency-symbol"]
    for currency_selector in currency_selectors:
        currency_el = await card.query_selector(currency_selector)
        if currency_el:
            currency_text = await currency_el.text_content()
            if currency_text and currency_text.strip():
                selectors["currency"] = {
                    "selector": currency_selector,
                    "sample": currency_text.strip()
                }
                break
    
    # Поиск локации/адреса
    location_selectors = ["span.poly-component__location", "p.ui-search-item__group__element", "span.ui-search-item__location-label"]
    for location_selector in location_selectors:
        location_el = await card.query_selector(location_selector)
        if location_el:
            location_text = await location_el.text_content()
            if location_text and location_text.strip():
                selectors["location"] = {
                    "selector": location_selector,
                    "sample": location_text.strip()
                }
                break
    
    # Поиск площади (часто указывается в атрибутах)
    area_selectors = ["li.poly-attributes-list__item", "ul.poly-attributes-list li", "div.poly-component__attributes-list li"]
    for area_selector in area_selectors:
        area_elements = await card.query_selector_all(area_selector)
        for area_el in area_elements:
            area_text = await area_el.text_content()
            if area_text and ('m²' in area_text or 'ha' in area_text.lower()):
                selectors["area"] = {
                    "selector": area_selector,
                    "sample": area_text.strip()
                }
                break
        if "area" in selectors:
            break
    
    # Поиск изображения
    image_selectors = ["img.poly-component__picture", "div.poly-card__portada img", "img"]
    for image_selector in image_selectors:
        img_el = await card.query_selector(image_selector)
        if img_el:
            # Проверяем атрибуты data-src и src
            for attr in ["data-src", "src"]:
                img_src = await img_el.get_attribute(attr)
                if img_src and img_src.startswith("http") and not img_src.startswith("data:"):
                    selectors["image"] = {
                        "selector": image_selector,
                        "attribute": attr,
                        "sample": img_src
                    }
                    break
            if "image" in selectors:
                break
    
    return selectors

async def analyze_site_structure():
    """Основная функция для анализа структуры сайта."""
    logger.info(f"Начало анализа страницы: {TARGET_URL}")
    
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        
        page = await context.new_page()
        
        # Переход на страницу
        try:
            logger.info(f"Переход на страницу: {TARGET_URL}")
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            logger.info("Страница загружена успешно")
            
            # Сохраняем скриншот и HTML
            if SAVE_ARTIFACTS:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                await save_screenshot(page, f"page_full_{timestamp}")
                await save_html(page, f"page_source_{timestamp}")
            
            # Анализ основных контейнеров
            main_containers = {
                "list_container": ["ol.ui-search-layout", "div.ui-search-layout", "div.ui-search-results"],
                "card_container": ["li.ui-search-layout__item", "div.ui-search-result__wrapper", "div.andes-card", 
                                  "div.ui-search-result--core", "div[class*='poly-card']"]
            }
            
            container_results = {}
            for container_type, selectors in main_containers.items():
                for selector in selectors:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        container_results[container_type] = {
                            "selector": selector,
                            "count": len(elements)
                        }
                        logger.info(f"Найден контейнер '{container_type}': {selector} (количество: {len(elements)})")
                        break
            
            if SAVE_ARTIFACTS:
                await save_json(container_results, "container_analysis")
            
            # Если найден контейнер карточек, анализируем его
            card_selector = container_results.get("card_container", {}).get("selector")
            if card_selector:
                # Сохраняем скриншот первых карточек
                cards = await page.query_selector_all(card_selector)
                if cards and len(cards) > 0:
                    for i, card in enumerate(cards[:3]):  # Первые 3 карточки
                        await card.screenshot(path=RESULTS_DIR / f"card_{i+1}.png")
                        logger.info(f"Сохранен скриншот карточки {i+1}")
                
                # Извлекаем селекторы из первой карточки
                card_selectors = await extract_selectors_from_card(page, card_selector)
                if card_selectors:
                    logger.info("Найдены следующие селекторы карточки:")
                    for key, value in card_selectors.items():
                        logger.info(f"- {key}: {value['selector']} (пример: {value.get('sample', '')[:30]}...)")
                    
                    if SAVE_ARTIFACTS:
                        await save_json(card_selectors, "card_selectors")
                
                # Анализ HTML-кода для определения общей структуры
                html_analysis = {
                    "page_title": await page.title(),
                    "main_elements": {}
                }
                
                # Анализируем основные части страницы
                main_elements = ["header", "footer", "nav", "aside", "section", "main"]
                for element in main_elements:
                    elements = await page.query_selector_all(element)
                    if elements:
                        html_analysis["main_elements"][element] = len(elements)
                
                if SAVE_ARTIFACTS:
                    await save_json(html_analysis, "html_structure_analysis")
            
            else:
                logger.warning("Не найден контейнер карточек. Возможно, структура сайта изменилась.")
                
                # Сохраняем список всех классов на странице для анализа
                classes = await page.evaluate("""() => {
                    const elements = document.querySelectorAll('*');
                    const classes = new Set();
                    elements.forEach(el => {
                        if (el.className && typeof el.className === 'string') {
                            el.className.split(' ').forEach(c => {
                                if (c) classes.add(c);
                            });
                        }
                    });
                    return Array.from(classes);
                }""")
                
                # Ищем классы, которые могут быть связаны с карточками товаров
                potential_card_classes = []
                pattern = re.compile(r'(card|item|result|product|listing)', re.IGNORECASE)
                for cls in classes:
                    if pattern.search(cls):
                        potential_card_classes.append(cls)
                
                logger.info(f"Найдено {len(potential_card_classes)} потенциальных классов карточек: {', '.join(potential_card_classes[:10])}...")
                
                if SAVE_ARTIFACTS:
                    await save_json({"all_classes": classes, "potential_card_classes": potential_card_classes}, "class_analysis")
            
        except Exception as e:
            logger.error(f"Ошибка при анализе страницы: {e}", exc_info=True)
            
            if SAVE_ARTIFACTS:
                # В случае ошибки сохраняем скриншот
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                try:
                    await save_screenshot(page, f"error_{timestamp}")
                except:
                    logger.error("Не удалось сохранить скриншот ошибки")
        
        finally:
            # Закрытие браузера
            await context.close()
            await browser.close()
            logger.info("Браузер закрыт")

async def main():
    """Основная функция."""
    logger.info("Начало анализа структуры MercadoLibre")
    await analyze_site_structure()
    logger.info("Анализ завершен")

if __name__ == "__main__":
    asyncio.run(main()) 