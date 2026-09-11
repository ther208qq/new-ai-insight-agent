"""反思结果 (ReflectionResult) 相关的 Pydantic schema。

本模块定义 LLM 对自身输出进行「反思 / 自检」时生成的结构化数据格式，
作为 LLM 世界与传统后端世界之间的边界。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.evidence import Evidence

IssueType = Literal[
    "factual_error",
    "unsupported_claim",
    "missing_evidence",
    "low_quality",
    "contradiction",
]


class ReflectionIssue(BaseModel):
    """单项反思问题。

    描述反思过程中发现的某一个具体问题点。
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="出问题的字段名")
    type: IssueType = Field(description="问题类型（固定枚举）")
    description: str = Field(description="问题描述")
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="支撑该问题的证据列表（Evidence 对象）",
    )


class ReflectionResult(BaseModel):
    """反思结果——用于评估 LLM 输出是否通过自检。"""

    model_config = ConfigDict(extra="forbid")

    passed: bool = Field(description="是否通过反思 / 自检")
    issues: list[ReflectionIssue] = Field(description="发现的问题列表")
    summary: str = Field(description="反思总结")


# ---------------------------------------------------------------------------
# LLM 侧草稿 (ReflectionDraft)
#
# 放在同一处的原因和 knowledge.py 里 ProposalDraft 一样：最终结构是给后端用
# 的，草稿是给 LLM 用的，两者的差别只有一处 ——
#
#   ReflectionIssue.evidence    最终结构里是 list[Evidence]（含正文），草稿里是
#                               list[int] 编号：正文就在传入的 evidence 里，
#                               代码按编号取原文回填。
#
# 让 LLM 直接输出 ReflectionResult 是行不通的，而且后果比提案那边更严重：
# Evidence 的四个字段全是自由文本，LLM 完全可以写出一份 State 里根本不存在的
# 证据，schema 校验不出任何问题。Reflection 的价值就在于「结论可回溯到证据」，
# 那样就没了 —— 见 graph/reflection.py。
# ---------------------------------------------------------------------------


class DraftReflectionIssue(BaseModel):
    """反思问题的草稿：evidence 用编号引用，正文由代码回填。"""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="出问题的字段名")
    type: IssueType = Field(description="问题类型（固定枚举）")
    description: str = Field(description="问题描述")
    evidence_refs: list[int] = Field(
        default_factory=list,
        description="支撑该问题的 Evidence 编号（Context 里的 [n]）",
    )


class ReflectionDraft(BaseModel):
    """LLM 输出的反思草稿。

    字段与 ReflectionResult 一一对应，数量与类型都保持一致 —— 校验在 LLM
    边界就发生，而不是拖到代码拼装成品时才炸。
    """

    model_config = ConfigDict(extra="forbid")

    passed: bool = Field(description="是否通过反思 / 自检")
    issues: list[DraftReflectionIssue] = Field(description="发现的问题列表")
    summary: str = Field(description="反思总结")
