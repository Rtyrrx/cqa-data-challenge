import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)


@dataclass
class Settings:
    db_path: Path
    provider: str = 'ollama'
    model: str = 'qwen3:4b'
    api_key: str = ''
    ollama_url: str = 'http://127.0.0.1:11434'
    dataset_url: str = ''
    dataset_group_id: str = 'DEV'
    auto_import: bool = True
    team_name: str = 'Your team'
    timeout: float = 300
    max_attempts: int = 3
    max_output_tokens: int = 2500
    ollama_context: int = 32768
    request_interval: float = 15
    token_budget: int = 160000
    require_review: bool = True
    evaluation_strategy: str = 'auto'

    @classmethod
    def from_env(cls):
        provider = os.getenv('CQA_PROVIDER', 'ollama')
        settings = cls(
            db_path=Path(os.getenv('CQA_DB_PATH', str(ROOT / 'data' / 'cqa.sqlite3'))),
            provider=provider,
            model=os.getenv('CQA_MODEL', 'openai/gpt-oss-120b' if provider == 'groq' else 'qwen3:4b'),
            api_key=os.getenv('GROQ_API_KEY', ''),
            ollama_url=os.getenv('CQA_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/'),
            dataset_url=os.getenv('CQA_DATASET_URL', ''),
            dataset_group_id=os.getenv('CQA_DATASET_GROUP_ID', 'DEV'),
            auto_import=os.getenv('CQA_AUTO_IMPORT','true').lower() not in ('false','0','no'),
            team_name=os.getenv('CQA_TEAM_NAME', 'Your team'),
            timeout=float(os.getenv('CQA_TIMEOUT', '300')),
            max_attempts=int(os.getenv('CQA_MAX_ATTEMPTS', '3')),
            max_output_tokens=int(os.getenv('CQA_MAX_OUTPUT_TOKENS', '2500')),
            ollama_context=int(os.getenv('CQA_OLLAMA_CONTEXT', '32768')),
            request_interval=float(os.getenv('CQA_REQUEST_INTERVAL', '15')),
            token_budget=int(os.getenv('CQA_TOKEN_BUDGET', '160000')),
            require_review=os.getenv('CQA_REQUIRE_REVIEW','true').lower() not in ('false','0','no'),
            evaluation_strategy=os.getenv('CQA_EVALUATION_STRATEGY','auto'),
        )
        if settings.provider not in ('ollama', 'groq'):
            raise ValueError('CQA_PROVIDER must be ollama or groq')
        if settings.evaluation_strategy not in ('auto','criterion','single'):
            raise ValueError('CQA_EVALUATION_STRATEGY must be auto, criterion or single')
        if settings.max_attempts not in range(1, 6):
            raise ValueError('CQA_MAX_ATTEMPTS must be 1..5')
        if min(settings.timeout, settings.max_output_tokens, settings.ollama_context) <= 0:
            raise ValueError('Timeout, output tokens, and context must be positive')
        if settings.request_interval < 0 or settings.token_budget < 0:
            raise ValueError('Interval and token budget cannot be negative')
        return settings
