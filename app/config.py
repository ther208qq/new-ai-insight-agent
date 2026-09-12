"""从 .env 读取配置。

配置只在这里读、并且读出来就校验：少一个环境变量应该在这里报错，
而不是等到调 LLM 时冒出一句看不懂的 401。其余代码拿到的都是校验过的对象，
不直接碰 os.environ。

真实环境变量优先于 .env（load_dotenv 的 override=False），方便部署时覆盖。
.env 不提交，格式见 .env.example。

这里读三类配置，必填性刻意不同：LLM 端点参数（LLMSettings）缺了就跑不动，
所以少一个都报错；GitHub token（GitHubSettings）与日志级别（LogSettings）都是
选填的，缺了只是少点能力/可观测性，回落到默认值即可 —— 见各自的 load_*。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


DEFAULT_LOG_LEVEL = "INFO"

# 变量名带 ai_insight_ 前缀是刻意的：LOG_LEVEL 太通用，部署平台（Docker / K8s /
# 各家 PaaS）的环境里很可能已经有一个同名的、管着别的东西 —— 而真实环境变量优先于
# .env，撞上了就会静默按别人的值走，日志级别莫名其妙。前缀把它变成这个项目私有的。
LOG_LEVEL_ENV_VAR = "AI_INSIGHT_LOG_LEVEL"

# 写死而不是 logging.getLevelNamesMapping()：那个 3.11 才有，本项目是 3.10。
# 也别写成 logging 模块里的常量，这里只关心「哪些名字算合法」。
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def normalize_log_level(value: str) -> str:
    """去空白 + 转大写 + 校验，返回规范的级别名。

    大小写不敏感是刻意的：.env 里写小写是常态，而 logging.Logger.setLevel()
    只认大写精确匹配（setLevel("info") 会抛 ValueError）。

    校验只此一处：LogSettings 的 validator 与 app/logging.py 的 _coerce_level()
    共用它，避免「哪些级别算合法」有两份、哪天加一档时漏改一边。
    放在 config.py 而不是 logging.py，是为了不让两个模块互相 import。
    """
    normalized = value.strip().upper()
    if normalized not in LOG_LEVELS:
        raise ValueError(f"未知日志级别 {value!r}，可用：{'/'.join(LOG_LEVELS)}")
    return normalized


class LogSettings(BaseModel):
    """日志配置。目前只有级别一项，配成对象是为了和 LLMSettings 同一形状 ——
    调用方（main.py）拿到的都是校验过的对象，不必知道背后读的是哪个变量。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: str = Field(
        default=DEFAULT_LOG_LEVEL,
        description="AI_INSIGHT_LOG_LEVEL（DEBUG / INFO / WARNING / ERROR / CRITICAL）",
    )

    @field_validator("level")
    @classmethod
    def _normalize_level(cls, value: str) -> str:
        # 校验放这里，错误就由 pydantic 报成一条指名道姓的 ValidationError，
        # 再由 load_log_settings 转成 ConfigError —— 和上面把数字型字段交给
        # pydantic 转换是同一个理由。
        return normalize_log_level(value)


def load_log_settings(*, env_path: Path | None = None) -> LogSettings:
    """读取 .env（或真实环境变量）里的 AI_INSIGHT_LOG_LEVEL，返回 LogSettings。

    env_path 只给测试用；不传就读项目根目录下的 .env。

    和 load_llm_settings 有一处刻意的不同：**不做必填检查**。日志级别是选填的，
    没写 .env、甚至 .env 根本不存在（CI 就是），都回落到 INFO。日志级别猜一个总比
    「连日志都起不来」好 —— 必填检查那条纪律要解决的是「缺了就跑不动的东西」，
    这里不适用。
    """
    path = env_path or ENV_PATH
    load_dotenv(path, override=False)

    try:
        return LogSettings(level=os.getenv(LOG_LEVEL_ENV_VAR) or DEFAULT_LOG_LEVEL)
    except ValidationError as error:
        raise ConfigError(f"{LOG_LEVEL_ENV_VAR} 配置不合法：{error}") from error


# 不带 ai_insight_ 前缀（与 LOG_LEVEL_ENV_VAR 相反）：GITHUB_TOKEN 是 GitHub
# 生态的通用名字，gh CLI / Actions / CI 都认，改成私有的反而对不上工具链。
GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"


class GitHubSettings(BaseModel):
    """访问 GitHub API 的配置。目前只有 token 一项。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str | None = Field(
        default=None,
        description="GITHUB_TOKEN。选填：公开仓库不配也能读，只是限流额度低",
    )


def load_github_settings(*, env_path: Path | None = None) -> GitHubSettings:
    """读取 .env（或真实环境变量）里的 GITHUB_TOKEN，返回 GitHubSettings。

    env_path 只给测试用；不传就读项目根目录下的 .env。

    读取必须和 load_dotenv 在同一个函数里：token 是 Tool 运行时才读的，不像
    LLMSettings 那样在 main.py 启动时就被取走。指望别的模块先调过 load_dotenv
    的话，「在 config 加载之前调 Tool」的路径会静默降级成匿名请求，再以「限流」
    的面目失败 —— 报错还误导人去配 token，而 token 明明配了。

    不做必填检查、也不做格式校验：公开仓库不带 token 能读，只是额度低；token
    形态有好几种（ghp_ / github_pat_ / …）还允许自定义，硬套前缀只会误伤，
    真写错了 GitHub 会回 401。
    """
    path = env_path or ENV_PATH
    load_dotenv(path, override=False)

    # strip()：从文件 export 进来的环境变量常带尾随换行，带进 header 会认证失败
    # 得莫名其妙。空串归一成 None，省得调用方既要判空又要判 None。
    token = (os.getenv(GITHUB_TOKEN_ENV_VAR) or "").strip()
    return GitHubSettings(token=token or None)
