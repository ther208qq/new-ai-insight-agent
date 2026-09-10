"""Tool 目录。

这里只登记「有哪些 Tool、各自能做什么」，供 Agent 组织 Prompt 时使用，
让工具清单只有一个来源，不必在提示词里再抄一遍。真正的实现在同目录各模块里。

注意：登记 ≠ 实现，也 ≠ 可执行 —— 哪些 Tool 能真正执行见 registry.ALLOWED_TOOLS。
"""

from app.tools.registry import (
    ALLOWED_TOOLS,
    UnsupportedToolError,
    call_tool,
)

# 这些描述会原样进入 Prompt（见 agents/prompts.py），标题是「当前可用工具」。
# 所以只写「这个 Tool 能做什么」，不写实现状态 —— 在「可用工具」下面标注
# 「尚未实现」会让模型收到自相矛盾的信号。
TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_project_metadata": "获取仓库基础元数据（名称、描述、语言、star 数、topics）",
    "get_readme": "获取仓库 README 的内容",
    "get_project_structure": "获取仓库的目录结构",
    "get_file": "读取仓库中指定文件的内容",
    "search_code": "在仓库代码中搜索关键词",
}

__all__ = [
    "TOOL_DESCRIPTIONS",
    "ALLOWED_TOOLS",
    "UnsupportedToolError",
    "call_tool",
]
