"""从 .env 读取配置。

配置只在这里读、并且读出来就校验：少一个环境变量应该在这里报错，
而不是等到调 LLM 时冒出一句看不懂的 401。其余代码拿到的都是校验过的对象，
不直接碰 os.environ。

真实环境变量优先于 .env（load_dotenv 的 override=False），方便部署时覆盖。
.env 不提交，格式见 .env.example。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# 没有不行的那几个。缺了直接给明确提示，不必等 pydantic 报一堆字段错。
_REQUIRED_ENV_VARS = ("LLM_API_KEY", "LLM_MODEL")


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


class LLMSettings(BaseModel):
    """OpenAI 兼容端点的连接参数。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: str = Field(min_length=1, description="LLM_API_KEY")
    model: str = Field(min_length=1, description="LLM_MODEL")
    base_url: str | None = Field(
        default=None,
        description="LLM_BASE_URL，留空则用 openai 包的默认地址",
    )
    timeout: float = Field(default=60.0, gt=0, description="LLM_TIMEOUT（秒）")
    max_tokens: int | None = Field(
        default=None,
        gt=0,
        description="LLM_MAX_TOKENS，留空则不传该参数、由服务端决定",
    )
    temperature: float = Field(
        default=0.0,
        ge=0,
        le=2,
        description="LLM_TEMPERATURE，默认 0：这一步要的是稳定复现，不是创造力",
    )


def load_llm_settings(*, env_path: Path | None = None) -> LLMSettings:
    """读取 .env（或真实环境变量）并校验，返回 LLMSettings。

    env_path 只给测试用；不传就读项目根目录下的 .env。
    """
    path = env_path or ENV_PATH
    load_dotenv(path, override=False)

    missing = [name for name in _REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        raise ConfigError(
            f"缺少环境变量 {missing}：请把 .env.example 复制成 .env 并填写"
            f"（预期位置 {path}）"
        )

    # 数字型字段交给 pydantic 转换：写错了会得到一条指名道姓的校验错误，
    # 比 int()/float() 抛的 ValueError 好认。
    try:
        return LLMSettings(
            api_key=os.environ["LLM_API_KEY"],
            model=os.environ["LLM_MODEL"],
            base_url=os.getenv("LLM_BASE_URL") or None,
            timeout=os.getenv("LLM_TIMEOUT") or 60.0,
            max_tokens=os.getenv("LLM_MAX_TOKENS") or None,
            temperature=os.getenv("LLM_TEMPERATURE") or 0.0,
        )
    except ValidationError as error:
        raise ConfigError(f"LLM 配置不合法：{error}") from error
