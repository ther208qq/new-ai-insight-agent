"""反思结果 (ReflectionResult) 相关的 Pydantic schema。

本模块定义 LLM 对自身输出进行「反思 / 自检」时生成的结构化数据格式，
作为 LLM 世界与传统后端世界之间的边界。
"""

from pydantic import BaseModel, ConfigDict, Field


class ReflectionIssue(BaseModel):
    """单项反思问题。

    描述反思过程中发现的某一个具体问题点。
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="出问题的字段名")
    type: str = Field(description="问题类型，例如 缺失字段 / 类型错误 / 逻辑错误")
    description: str = Field(description="问题描述")
    evidence: str = Field(description="支撑该问题的证据 / 依据")


class ReflectionResult(BaseModel):
    """反思结果——用于评估 LLM 输出是否通过自检。"""

    model_config = ConfigDict(extra="forbid")

    passed: bool = Field(description="是否通过反思 / 自检")
    issues: list[ReflectionIssue] = Field(description="发现的问题列表")
    summary: str = Field(description="反思总结")
