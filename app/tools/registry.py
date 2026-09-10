"""Tool 注册与调用。

AgentDecision 里只有 tool_name 和 tool_arguments 两个字符串/字典，
这里负责把它们落成一次真实的 Tool 调用：

    name → Tool 函数   （ALLOWED_TOOLS）
    Tool 函数 + arguments → Tool Result

参数处理有一条固定策略：**所有 Tool 都取自同一个仓库**，所以 owner / repo
永远以当前 State 的来源为准，调用方（也就是 LLM）在 tool_arguments 里写的
owner / repo 一律忽略。这不是多余的防御 —— LLM 完全可能把 owner / repo
填错、漏填，或填成它从 README 里看到（但并不属于本仓库）的名字。
如果哪天需要跨仓库取证，再放开这条限制。

registry 与 TOOL_DESCRIPTIONS 的分工：那边描述「有什么、能干什么」（给 LLM
看），这边决定「谁能被真正执行」（给后端用）。两个清单目前并不一样 ——
get_project_metadata / get_readme 对 LLM 可见却不在 ALLOWED_TOOLS 里，
因为它们只由 run() 直接调用，没接进执行层。
"""

import inspect
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.tools.get_file import get_file
from app.tools.get_project_structure import get_project_structure
from app.tools.search_code import search_code

# 仓库级参数：由 State 提供，不接受调用方传值
REPO_PARAMS = ("owner", "repo")

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
    """按 tool_name 找到 Tool 并执行，返回原始 Tool Result。"""
    if tool_name not in ALLOWED_TOOLS:
        raise UnsupportedToolError(
            f"不支持的 Tool: {tool_name!r}；当前可执行的 Tool 只有 "
            f"{sorted(ALLOWED_TOOLS)}"
        )

    arguments = dict(tool_arguments or {})
    _reject_invalid_arguments(tool_name, arguments)

    # owner / repo 由调用方传入，覆盖 LLM 写的值
    arguments["owner"] = owner
    arguments["repo"] = repo

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
        raise UnsupportedToolError(
            f"Tool {tool_name!r} 不接受参数 {sorted(unknown)}，"
            f"可用参数: {sorted(parameter_names)}"
        )

    missing = required - set(arguments)
    if missing:
        raise UnsupportedToolError(
            f"Tool {tool_name!r} 缺少必填参数 {sorted(missing)}"
        )


@lru_cache(maxsize=None)
def _parameter_names(tool: Callable[..., Any]) -> frozenset[str]:
    return frozenset(inspect.signature(tool).parameters)
