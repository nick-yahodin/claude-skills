from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    PROJECT_NAME: str = "UruguayLands Parser"
    TELEGRAM_DELAY_SECONDS: int = 2 # Задержка между отправками в Telegram

    # Переменные из .env (хотя они загружаются и в telegram_poster)
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    CHAT_ID: str = os.getenv('CHAT_ID', '')

    class Config:
        # Указываем путь к .env относительно корня проекта,
        # если Pydantic будет его загружать (хотя мы и так делаем load_dotenv)
        env_file = os.path.join(os.path.dirname(__file__), '..', 'config', '.env')
        env_file_encoding = 'utf-8'
        extra = 'ignore' # Игнорировать лишние переменные в .env

settings = Settings() 