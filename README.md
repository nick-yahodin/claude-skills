# UruguayLands

Парсер земельных участков в Уругвае с MercadoLibre → Telegram.

## Архитектура

**API-first подход**: вместо Playwright используется публичный API MercadoLibre — быстрее, надёжнее, без блокировок.

```
main.py          → точка входа, CLI
scraper.py       → поиск + детали через API
duplicate_checker.py → фильтрация дубликатов  
telegram_bot.py  → отправка в Telegram
models.py        → модель Listing (Pydantic)
config.py        → конфигурация из .env
```

## Установка

```bash
pip install -r requirements.txt
cp .env.example .env
# Заполнить .env своими данными
```

## Использование

```bash
# Полный цикл
python main.py

# Только парсинг, без Telegram
python main.py --no-send

# С фильтром по цене
python main.py --min-price 5000 --max-price 50000

# Экспорт в файл
python main.py --export results.json --no-send

# Максимум 10 объявлений, режим отладки
python main.py --max 10 --debug
```

## Что извлекается

| Поле | Источник |
|------|----------|
| Название, цена, валюта | API search |
| Координаты GPS | API items |
| Все фото (до 20) | API items |
| Площадь, цена за м² | API attributes |
| Коммуникации | API attributes + описание |
| Зонирование | API attributes + описание |
| Продавец | API items |
| Дата публикации | API items |
| Описание | API description |
