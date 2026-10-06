from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""

    planner_model: str = ""
    writer_model: str = ""
    judge_model: str = ""

    tavily_api_key: str = ""
    tavily_mcp_url: str = "https://mcp.tavily.com/mcp/"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/research_agent"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "development"

    results_dir: Path = PROJECT_ROOT / "results"


settings = Settings()
