# UruguayLands

Автоматический парсер объявлений о продаже земельных участков в Уругвае с отправкой в Telegram-канал @uruguayland.

## Текущий статус проекта

Проект находится в стадии активной отладки. Основные компоненты:

- ✅ Парсер MercadoLibre: работает, корректно извлекает данные объявлений
- ✅ Отправка в Telegram: работает через прямой API и python-telegram-bot как запасной вариант
- ⚠️ Парсер Gallito: добавлен механизм обхода Cloudflare (требует тестирования)
- ⚠️ Парсер Infocasas: улучшена надежность парсинга (требует тестирования)

## Описание

Проект автоматически:
1. Парсит сайты недвижимости Уругвая (MercadoLibre, Gallito, Infocasas)
2. Извлекает данные объявлений о продаже земельных участков
3. Отправляет новые объявления в Telegram-канал @uruguayland

## Установка и настройка

### Требования
- Python 3.9+
- Доступ к API Telegram (токен бота и ID чата)
- Установленные зависимости из requirements.txt

### Установка

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd UruguayLands
```

2. Создайте и активируйте виртуальное окружение:
```bash
python -m venv .venv
source .venv/bin/activate  # для Linux/Mac
# или
.venv\Scripts\activate  # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Установите Playwright и браузеры:
```bash
python -m playwright install firefox
```

5. Создайте файл конфигурации `.env` в директории `config/`:
```bash
cp config/.env.example config/.env
```

6. Отредактируйте файл `config/.env` и укажите свои параметры:
```
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_telegram_chat_id
CHECK_INTERVAL_MINUTES=60
PARSERS_TO_RUN=mercadolibre,gallito,infocasas
LOG_LEVEL=INFO
MAX_PAGES_PER_RUN=2
TELEGRAM_DELAY_SECONDS=10
HEADLESS_MODE=true
```

## Запуск

```bash
python app/main.py
```

## Архитектура проекта

```
UruguayLands/
├── app/
│   ├── main.py              # Основной скрипт
│   ├── listing_manager.py   # Менеджер объявлений
│   ├── telegram_poster.py   # Отправка в Telegram
│   ├── hashtag_generator.py # Генератор хештегов
│   ├── models.py            # Модели данных
│   └── parsers/             # Модули парсеров
│       ├── base.py           # Базовый класс парсера
│       ├── mercadolibre.py   # Парсер MercadoLibre 
│       ├── gallito.py        # Парсер Gallito с обходом Cloudflare
│       └── infocasas.py      # Парсер InfoCasas
├── config/                  # Конфигурация
│   ├── .env.example          # Пример конфигурации
│   └── .env                  # Фактическая конфигурация (не в git)
├── data/                    # Директория для данных
│   └── posted_listings.json  # Список обработанных объявлений
└── logs/                    # Логи работы приложения
```

## Решенные проблемы

1. **Отправка в Telegram**: Реализовано два метода отправки:
   - Прямой метод через requests API (основной)
   - Через python-telegram-bot (запасной)

2. **Обход Cloudflare**: Добавлен механизм обхода защиты Cloudflare:
   - Увеличенные паузы между запросами
   - Эмуляция человеческого поведения
   - Работа в режиме без headless

3. **Улучшенная стабильность** парсера InfoCasas:
   - Гибкий подход к селекторам
   - Повторные попытки при ошибках
   - Расширенное логирование

## Текущие проблемы и ограничения

1. Парсер Gallito сталкивается с защитой Cloudflare - добавлен механизм обхода, но требует тестирования
2. Парсер InfoCasas может не найти элементы на странице - добавлены альтернативные селекторы

## Дальнейшее развитие

1. Тестирование и улучшение парсеров Gallito и InfoCasas
2. Добавление новых источников данных
3. Улучшение форматирования сообщений в Telegram
4. Добавление аналитики и статистики по новым объявлениям
