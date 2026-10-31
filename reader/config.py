import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    base_url: str
    api_key: str
    model: str
    strict_tools: bool = False
    require_tool_choice: bool = True
    enable_thinking: Optional[bool] = None

    @property
    def configured(self):
        return bool(self.base_url and self.api_key and self.model)


def settings():
    # Re-read on every request, so configuring .env does not require a restart.
    values = dotenv_values(ROOT / '.env')
    def get(name, default=''):
        return (os.getenv(name) or values.get(name) or default).strip()
    thinking = get('OPENAI_ENABLE_THINKING').lower()
    return Settings(get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/'),
                    get('OPENAI_API_KEY'), get('OPENAI_MODEL'),
                    get('OPENAI_STRICT_TOOLS', 'false').lower() == 'true',
                    get('OPENAI_REQUIRE_TOOL_CHOICE', 'true').lower() == 'true',
                    None if not thinking else thinking == 'true')
