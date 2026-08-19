from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "GEO Platform"
    database_url: str = "sqlite:///./geo_v0.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    wenxin_api_key: str = ""
    wenxin_secret_key: str = ""
    wenxin_model: str = "ernie-4.0-turbo-8k"
    wenxin_access_token_url: str = "https://aip.baidubce.com/oauth/2.0/token"
    wenxin_endpoint_template: str = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{model}"
    wenxin_timeout_seconds: int = 60
    monitoring_artifact_dir: str = "./artifacts/monitoring"
    redis_url: str = "redis://localhost:6379/0"
    app_timezone: str = "Asia/Shanghai"
    wenxin_profile_dir: str = "./runtime/wenxin-profile"
    wenxin_web_url: str = "https://chat.baidu.com/"
    wenxin_headless: bool = False
    wenxin_browser_timeout_seconds: int = 300
    wenxin_answer_timeout_seconds: int = 120
    wenxin_max_concurrency: int = 1
    wenxin_max_retries: int = 2
    reference_resolution_min_rate: float = 0.95
    reference_title_fuzzy_threshold: float = 0.72
    minimum_retrieval_candidate_count: int = 30
    strategy_llm_provider: str = "local_rule"
    strategy_llm_model: str = "local-rule-v1"
    strategy_llm_prompt_version: str = "strategy_prompt.v1"
    # Runtime Semantic LLM (DeepSeek) — 全部来自环境变量，代码不写死
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: int = 120
    semantic_case_max_calls: int = 200
    semantic_case_max_tokens: int = 2_000_000

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
