"""Tool 注册与调用。

AgentDecision 里只有 tool_name 和 tool_arguments 两个字符串/字典，
这里负责把它们落成一次真实的 Tool 调用：

    name → Tool 函数   （ALLOWED_TOOLS）
    Tool 函数 + arguments → Tool Result

参数处理有一条固定策略：**所有 Tool 都取自同一个仓库**，所以仓库地址永远以
当前 State 的来源为准，调用方（也就是 LLM）在 tool_arguments 里写的仓库参数
一律忽略。这不是多余的防御 —— LLM 完全可能把它填错、漏填，或填成它从 README
里看到（但并不属于本仓库）的名字。如果哪天需要跨仓库取证，再放开这条限制。

仓库参数是单个 url：三个 Tool 都收 url，registry 不必按 Tool 分辨该注入什么。

registry 与 TOOL_DESCRIPTIONS 的分工：那边描述「有什么、能干什么」（给 LLM
看），这边决定「谁能被真正执行」（给后端用）。两个清单目前并不一样 ——
get_project_metadata / get_readme 对 LLM 可见却不在 ALLOWED_TOOLS 里，
因为它们只由 run() 直接调用，没接进执行层。
"""

import inspect
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.logging import get_logger
from app.tools.get_file import get_file
from app.tools.get_project_structure import get_project_structure
from app.tools.search_code import search_code

logger = get_logger("tools.registry")

# 仓库级参数：由 State 提供，不接受调用方传值。只有一个 —— 见模块 docstring。
REPO_PARAMS = ("url",)

ALLOWED_TOOLS: dict[str, Callable[..., Any]] = {
    "get_project_structure": get_project_structure,
    "get_file": get_file,
    "search_code": search_code,
}


class UnsupportedToolError(ValueError):
    """AgentDecision 指名的 Tool 不在可执行名单里。"""


def call_tool(
    tool_name: str,
    tool_arguments: dict[str, Any] | None,
    *,
    owner: str,
    repo: str,
) -> Any:
    """按 tool_name 找到 Tool 并执行，返回原始 Tool Result。

    这是全仓库 Tool 执行的唯一收口点，所以日志也只在这里打一处 —— 逐个 Tool 文件
    各打一次，等于把同一件事说 N 遍，还得跟着 ALLOWED_TOOLS 一起改。
    """
    if tool_name not in ALLOWED_TOOLS:
        # 异常里已经写了原因，这里再留一条不是重复：investigate() 不捕这个异常，
        # 它一路冒到 main.py 变成一行 print，中间过程就没了 —— 而「从第几轮开始
        # 乱点名」恰恰是轨迹里最该看见的东西。
        logger.warning(
            "不支持的 Tool：%r（当前可执行：%s）", tool_name, sorted(ALLOWED_TOOLS)
        )
        raise UnsupportedToolError(
            f"不支持的 Tool: {tool_name!r}；当前可执行的 Tool 只有 "
            f"{sorted(ALLOWED_TOOLS)}"
        )

    arguments = dict(tool_arguments or {})
    _reject_invalid_arguments(tool_name, arguments)

    # url 由调用方传入，覆盖 LLM 写的值。覆盖**之前**先记下它到底写了什么 ——
    # 覆盖之后就看不出来了，而这正是「LLM 把仓库填错」唯一的线索。
    supplied = sorted(set(arguments) & set(REPO_PARAMS))
    arguments["url"] = f"https://github.com/{owner}/{repo}"
    if supplied:
        logger.debug(
            "忽略 LLM 写的 %s，改用当前 State 的仓库 %s/%s", supplied, owner, repo
        )

    params = {k: v for k, v in arguments.items() if k not in REPO_PARAMS}
    logger.info("Tool 调用：%s（参数 %s，仓库 %s/%s）", tool_name, params, owner, repo)

    return ALLOWED_TOOLS[tool_name](**arguments)


def _reject_invalid_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """拒绝多余参数，并检查必填参数是否齐全。

    **arguments 会把参数错误变成 TypeError，但报错信息里不会说明是哪个
    Tool、LLM 到底传了什么 —— 而这里的调用方是 LLM，参数写错是常态，
    所以自己校验一遍，把 tool_name 和 tool_arguments 原样带进错误里。
    """
    parameter_names = _parameter_names(ALLOWED_TOOLS[tool_name])
    required = parameter_names - set(REPO_PARAMS)

    unknown = set(arguments) - set(parameter_names)
    if unknown:
        logger.warning(
            "Tool %r 不接受参数 %s（可用：%s）",
            tool_name,
            sorted(unknown),
            sorted(parameter_names),
        )
        raise UnsupportedToolError(
            f"Tool {tool_name!r} 不接受参数 {sorted(unknown)}，"
            f"可用参数: {sorted(parameter_names)}"
        )

    missing = required - set(arguments)
    if missing:
        logger.warning("Tool %r 缺少必填参数 %s", tool_name, sorted(missing))
        raise UnsupportedToolError(
            f"Tool {tool_name!r} 缺少必填参数 {sorted(missing)}"
        )


@lru_cache(maxsize=None)
def _parameter_names(tool: Callable[..., Any]) -> frozenset[str]:
    return frozenset(inspect.signature(tool).parameters)
