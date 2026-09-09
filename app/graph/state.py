"""知识处理过程状态 (KnowledgeProcessState) 相关的 Pydantic schema。

KnowledgeProcessState 是 graph 过程中的状态：它随 graph 节点流转，
记录一条知识从采集到落库的完整中间态
(collecting → analyzing → reflecting → persisting → relating → completed / failed)。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.evidence import Evidence
from app.schemas.knowledge import KnowledgeProposal
from app.schemas.reflection import ReflectionResult
from app.schemas.relation import RelationProposal

ProcessStatus = Literal[
    "collecting",
    "analyzing",
    "reflecting",
    "persisting",
    "relating",
    "completed",
    "failed",
]


class Source(BaseModel):
    """知识来源。"""

    url: str = Field(description="来源 URL")
    type: str = Field(description="来源类型")
    metadata: dict[str, Any] = Field(default_factory=dict, description="来源元数据")


class KnowledgeProcessState(BaseModel):
    """知识处理过程状态——graph 节点间流转的中间态。"""

    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(description="处理过程 ID")
    source: Source = Field(description="知识来源")
    evidence: list[Evidence] = Field(default_factory=list, description="证据列表")

    proposal: KnowledgeProposal | None = Field(default=None, description="知识提案")
    reflection_result: ReflectionResult | None = Field(default=None, description="反思结果")

    iteration_count: int = Field(default=0, description="迭代次数")
    tool_call_count: int = Field(default=0, description="工具调用次数")

    knowledge_id: str | None = Field(default=None, description="落库后的知识 ID")
    candidate_knowledge_ids: list[str] = Field(
        default_factory=list, description="候选知识 ID 列表"
    )
    relation_proposals: list[RelationProposal] = Field(
        default_factory=list, description="关系提案列表"
    )

    status: ProcessStatus = Field(description="处理状态（固定枚举）")
    error: str | None = Field(default=None, description="错误信息，仅在 failed 时非空")
