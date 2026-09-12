"""把「一次 Agent 运行发生了什么」写成人能读的日志。

定位是**调试追踪**，不是审计流：记的是 LLM 选了哪个 Tool、为什么停、反思判 pass
还是 retry、走到第几轮、LLM 客户端降到了哪一档、Context 在哪一刻被截断。所以格式
是单行文本、时间只到秒、默认写 stderr —— stdout 留给 main.py 那份中文报告（那是
运行结果，不是过程；混在一起就没法 `python main.py > out.txt` 了）。

用标准库 logging：不自造轮子，也不引第三方日志库（requirements.txt 的依赖清单不是
能随手加长的）。

关于文件名
----------
叫 app/logging.py 而不是 app/logging_config.py：绝对导入（PEP 328）下 app/ 里任何
`import logging` 拿到的都是标准库，本模块内部第一行也正是它，所以不产生遮蔽 —— 只要
从项目根跑（main.py 与 pytest 都是），sys.path[0] 就是根目录，而根目录下没有
logging.py。唯一的坑是「在 app/ 目录里跑脚本」，本项目没有这种入口。生态先例：
flask/logging.py。

关于配置在哪读
--------------
LOG_LEVEL 只有 config.load_log_settings() 一处读。configure_logging() **自己不读
env**：它的默认是常量 INFO，想按 .env 配就由调用方传进来（main.py 那一行）。这样
装配与读取分开，测试里 configure_logging(level="DEBUG") 就是全部 —— 不必 monkeypatch
环境变量，也不会因为某台机器 .env 里写了 LOG_LEVEL=DEBUG 而让断言忽明忽暗。

关于不做什么
------------
不调 logging.basicConfig()：它动的是 root logger，会把 pytest / 宿主程序的日志配置
一起改掉，而且 root 已经有 handler 时它静默什么都不做 —— 两条都不适合一个库里的
模块。也不碰 logger.handlers 里不是自己装的 handler（见 configure_logging）。
"""

import logging
import sys
from typing import IO

from app.config import DEFAULT_LOG_LEVEL, LogSettings, normalize_log_level

# 本项目的 logger 树根。一条 LOG_LEVEL 设在它上面就能控制全部：子 logger 的 level
# 都是 NOTSET，实际级别从这一层继承。
LOGGER_ROOT = "ai_insight"

# 面向人读：时间只到秒（一次运行是分钟级的，日期是审计流才需要的东西）、级别定宽
# 对齐、logger 名放中间（它是最能说明「谁在说话」的一列）。
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%H:%M:%S"

# 自有 handler 的标记属性。判定「这个 handler 是不是 configure_logging 装的」靠它，
# 而不是靠位置或数量 —— 这样 pytest 的 handler、宿主程序自己加的都不会被误摘。
_OWN_HANDLER_MARK = "_ai_insight_own_handler"


def get_logger(name: str) -> logging.Logger:
    """取本项目的 logger，name 传短名（"agent.knowledge"、"llm.openai"）。

    不传 __name__：模块名是 app.agents.knowledge_agent，那样树根会叫 "app"、名字里
    还带着文件名，看不出「哪一层在说话」。显式短名让日志一眼分层。粒度的约定是
    **一个模块一个 logger**，不要细到函数，也不要跨模块复用同一个名字。

    本函数无副作用：没调过 configure_logging 时它照样返回 logger，只是 INFO 不会被
    输出（`ai_insight` 的 effective level 继承 root 的 WARNING，见 configure_logging）。
    """
    return logging.getLogger(f"{LOGGER_ROOT}.{name}")


def configure_logging(
    settings: LogSettings | None = None,
    *,
    level: str | int | None = None,
    stream: IO[str] | None = None,
) -> logging.Logger:
    """装好本项目这棵 logger 树的 handler，返回 ai_insight 这个 logger。

    幂等：重复调用只会先把上一次自己装的 handler 摘掉、再装一个新的，不会叠加
    （测试之间反复调用、宿主程序重复初始化都安全）。判定「自己装的」靠 handler 上的
    _OWN_HANDLER_MARK，不是 logger.handlers.clear() —— 后者会把别人的 handler 一起
    干掉（pytest 的 caplog 就挂在 root 上，宿主程序也可能自己加过）。

    级别优先级：level > settings.level > DEFAULT_LOG_LEVEL。
    **要静音就传 level="CRITICAL"**：本项目不打 CRITICAL，等于关掉 —— 比再加一个
    enabled 开关少一个概念。

    stream 省略时写 sys.stderr（见模块 docstring）。测试传一个 io.StringIO() 进来就能
    把日志抓下来，不必自己装 handler。

    不读 .env（见模块 docstring）：想按 .env 配就显式传 load_log_settings()。
    """
    resolved = _resolve_level(settings, level)

    logger = logging.getLogger(LOGGER_ROOT)
    # 级别必须设在**这一层**，不能只设 handler 的级别：级别检查发生在记录进入
    # 任何 handler 之前，未 configure 时 ai_insight 的 effective level 继承 root 的
    # WARNING，INFO 会被提前丢掉，handler 再宽松也收不到。
    logger.setLevel(resolved)
    # 显式写出默认值：handler 挂在本层，子 logger 的记录靠 propagate 走上来才会被
    # 处理；同时保留「上层也看得到」的性质（caplog 之类挂在 root 上）。
    logger.propagate = True

    for handler in _own_handlers(logger):
        logger.removeHandler(handler)
        # StreamHandler.close() 不关底下的 stream（FileHandler 才关），所以摘旧的
        # 是安全的 —— 测试传进来的 StringIO 不会被关掉，getvalue() 照常可读。
        handler.close()

    if stream is None:
        stream = sys.stderr
        _use_utf8_stderr()

    handler = logging.StreamHandler(stream)
    setattr(handler, _OWN_HANDLER_MARK, True)
    handler.setFormatter(
        logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
    )
    handler.setLevel(resolved)
    logger.addHandler(handler)

    return logger


def _resolve_level(settings: LogSettings | None, level: str | int | None) -> int:
    if level is not None:
        return _coerce_level(level)
    if settings is not None:
        return _coerce_level(settings.level)
    return _coerce_level(DEFAULT_LOG_LEVEL)


def _coerce_level(value: str | int) -> int:
    """级别归一成 int。

    字符串不能直接丢给 setLevel：它只认大写精确匹配，setLevel("info") 会抛
    ValueError: Unknown level: 'info'。归一化共用 config.normalize_log_level()，
    「哪些级别算合法」因此只有一份。
    """
    if isinstance(value, int):
        return value
    return getattr(logging, normalize_log_level(value))


def _own_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if getattr(h, _OWN_HANDLER_MARK, False)]


def _use_utf8_stderr() -> None:
    """让中文日志别把 stderr 的编码搞崩。

    和 main.py 对 stdout 做的是同一件事、同一个理由：errors="replace" 保证最差只是
    显示成问号，而不是让 logging 在写日志时抛 UnicodeEncodeError、被自己的异常处理
    吞成一行「--- Logging error ---」。

    只在自己默认用 sys.stderr 时做 —— 调用方显式传了 stream 就不去碰全局。pytest 会把
    sys.stderr 换成没有 reconfigure() 的对象，所以先 hasattr（main.py 同款写法）。
    """
    stderr = sys.stderr
    if stderr is not None and hasattr(stderr, "reconfigure"):
        stderr.reconfigure(encoding="utf-8", errors="replace")


__all__ = [
    "LOGGER_ROOT",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_DATE_FORMAT",
    "get_logger",
    "configure_logging",
]
