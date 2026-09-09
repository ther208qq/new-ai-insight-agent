"""关系提案 (RelationProposal) 相关的 Pydantic schema。

本模块定义 LLM 在两条知识之间建立关联时输出的结构化数据格式，
作为 LLM 世界与传统后端世界之间的边界。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RelationType = Literal[
    "uses",
    "implements",
    "extends",
    "alternative_to",
    "related_to",
    "depends_on",
    "similar_concept",
]


class RelationProposal(BaseModel):
    """关系提案——用于在两条知识之间建立关联。"""

    model_config = ConfigDict(extra="forbid")

    target_knowledge_id: str = Field(description="目标知识 ID")
    relation_type: RelationType = Field(description="关系类型（固定枚举）")
    reason: str = Field(description="建立该关系的理由")
    confidence: float | None = Field(
        default=None,
        gt=0,
        lt=1,
        description="置信度，取值范围 (0, 1)；为空表示未评估",
    )
