import os
from logging import getLogger
from typing import List
import yaml

from dotenv import load_dotenv
from pydantic.v1 import BaseSettings

logger = getLogger(__name__)


class AppSettings(BaseSettings):
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    OPENROUTER_API_KEY: str

    LANGUAGE_MODEL: str

    SYSTEM_PROMPT: str = None

    TELEGRAM_BOT_TOKEN: str

    ADMIN_USER_IDS: List[int] = []
    
    # Optional API keys for enhanced POI search (all have free tiers)
    FOURSQUARE_API_KEY: str = None
    LOCATIONIQ_API_KEY: str = None
    GEOAPIFY_API_KEY: str = None

    def load_prompts_from_yaml(self, yaml_file="prompts.yaml"):
        """Load prompts from the specified YAML file."""
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
        docs_dir = "data"
        yaml_file_full_path = os.path.join(root_dir, docs_dir, yaml_file)

        with open(yaml_file_full_path, "r", encoding="utf-8") as file:
            prompts = yaml.safe_load(file)

        self.SYSTEM_PROMPT = prompts.get("system_prompt", "")


logger.info("Loading environment variables from .env file.")
load_dotenv()

app_settings = AppSettings()
app_settings.load_prompts_from_yaml()
logger.info(f"CONFIG (LANGUAGE_MODEL): {app_settings.LANGUAGE_MODEL}")
logger.info(f"CONFIG (SYSTEM_PROMPT): {app_settings.SYSTEM_PROMPT}")
