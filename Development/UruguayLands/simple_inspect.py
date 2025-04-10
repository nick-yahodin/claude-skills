import asyncio
from playwright.async_api import async_playwright

async def main():
    playwright = await async_playwright().start()
    browser = await playwright.firefox.launch(headless=False)
    page = await browser.new_page()
    
    await page.goto("https://listado.mercadolibre.com.uy/inmuebles/terrenos/venta/")
    await page.wait_for_load_state("networkidle")
    
    # Находим карточки
    cards = await page.query_selector_all(".ui-search-layout__item")
    print(f"Найдено {len(cards)} карточек")
    
    if cards:
        first = cards[0]
        
        # Ищем все текстовые элементы в карточке
        text_elements = await first.query_selector_all("p, span, div, a")
        print(f"Найдено {len(text_elements)} текстовых элементов")
        
        # Выводим только непустые тексты
        print("\nТекстовые элементы в карточке:")
        for i, el in enumerate(text_elements):
            text = await el.inner_text()
            if text.strip():
                print(f"{i+1}. \"{text[:50]}\"")
        
        # Ищем ссылки
        links = await first.query_selector_all("a")
        print("\nСсылки в карточке:")
        for i, link in enumerate(links):
            href = await link.get_attribute("href")
            if href:
                print(f"Ссылка {i+1}: {href}")
                
        # Сохраняем скриншот карточки
        await first.screenshot(path="card_inspect.png")
        print("\nСкриншот первой карточки сохранен в card_inspect.png")
    
    await browser.close()
    await playwright.stop()

asyncio.run(main()) 