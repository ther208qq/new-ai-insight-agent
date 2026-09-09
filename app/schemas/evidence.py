"""证据 (Evidence) 相关的 Pydantic schema。

Evidence 是跨 schema 共享的数据结构：知识提案、反思结果、处理过程
都用它承载「某个结论的依据」，作为 LLM 世界与传统后端世界之间的边界。
"""

from typing import Literal

from pydantic import BaseModel, Field

EvidenceType = Literal["readme", "code", "metadata", "documentation", "other"]


class Evidence(BaseModel):
    """证据——支撑某个结论的具体出处。"""

    source: str = Field(description="证据来源")
    location: str = Field(description="证据位置 / 定位信息")
    content: str = Field(description="证据内容")
    evidence_type: EvidenceType = Field(description="证据类型（固定枚举）")
