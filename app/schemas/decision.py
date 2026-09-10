"""Agent 决策 (AgentDecision) 相关的 Pydantic schema。

本模块定义 Knowledge Agent 每一步「下一步做什么」的结构化决策格式，
作为 LLM 世界与传统后端世界之间的边界：LLM 只负责输出一个 AgentDecision，
由后端代码去校验并执行，LLM 不直接调用 Tool。

两种合法形态：
    action="tool_call" —— 调用一个 Tool，tool_name / tool_arguments 必填
    action="finish"    —— 结束本轮，tool_name / tool_arguments 均为 None
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ActionType = Literal["tool_call", "finish"]


class AgentDecision(BaseModel):
    """Agent 的单步决策。"""

    model_config = ConfigDict(extra="forbid")

    action: ActionType = Field(
        description="决策动作（固定枚举）：tool_call 调用工具 / finish 结束"
    )
    tool_name: str | None = Field(
        default=None,
        description="要调用的工具名，仅 action=tool_call 时非空",
    )
    tool_arguments: dict[str, Any] | None = Field(
        default=None,
        description="调用工具时传入的参数，仅 action=tool_call 时非空",
    )
