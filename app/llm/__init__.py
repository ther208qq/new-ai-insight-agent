from app.config import LLMSettings, load_llm_settings
from app.llm.client import LLMClient, LLMNotConfiguredError
from app.llm.fake import FakeLLM
from app.llm.openai_compatible import OpenAIClient


def create_llm_client(settings: LLMSettings | None = None) -> LLMClient:
    """按 .env 里的配置建一个真实 LLM 客户端。

    调用方（比如脚本入口）只需要这一句，不必知道背后是哪家：
        agent = KnowledgeAgent(owner, repo, llm=create_llm_client())
    """
    return OpenAIClient(settings or load_llm_settings())


__all__ = [
    "LLMClient",
    "LLMNotConfiguredError",
    "FakeLLM",
    "LLMSettings",
    "load_llm_settings",
    "OpenAIClient",
    "create_llm_client",
]
