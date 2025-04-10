import asyncio
from playwright.async_api import async_playwright

URL = 'https://terreno.mercadolibre.com.uy/MLU-690599348-lotes-en-design-village-barrio-privado-en-solanas-financiacion-del-100-a-sola-firma-_JM'

async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        try:
            print(f"Navigating to {URL}...")
            await page.goto(URL, wait_until='load', timeout=60000) # Wait for full load
            print("Page loaded. Getting content...")
            content = await page.content()
            print("\n--- HTML CONTENT START ---\n")
            print(content)
            print("\n--- HTML CONTENT END ---\n")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(main()) 