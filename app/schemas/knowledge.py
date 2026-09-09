"""知识提案 (KnowledgeProposal) 相关的 Pydantic schema。

本模块定义 LLM 生成「知识提案」时输出的结构化数据格式，
作为 LLM 世界与传统后端世界之间的边界 (见 CHANGELOG.md 的模块职责)。

通用约定：description 描述「是什么」，evidence[] 给出「为什么这么定」的
支撑证据列表，便于溯源与评审。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.evidence import Evidence

TechnologyCategory = Literal[
    "framework",
    "language",
    "database",
    "infrastructure",
    "library",
    "model",
    "other",
]


class Feature(BaseModel):
    """core_features 中单项核心功能的属性结构。

    description 描述该功能本身；evidence 是支撑它的证据 / 依据，
    例如用户诉求、数据表现、可行性调研。
    """

    description: str = Field(description="核心功能描述")
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="支撑该核心功能的证据 / 依据列表",
    )


class Technology(BaseModel):
    """单项技术栈。

    name / category 定义选型；evidence 是支撑该选型的证据 / 依据列表：
    为什么选择这项技术、有什么依据。
    """

    name: str = Field(description="技术名称，例如 FastAPI、PostgreSQL、Redis")
    category: TechnologyCategory = Field(
        description=(
            "技术分类（固定枚举）：framework / language / database / "
            "infrastructure / library / model / other"
        )
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="支撑该选型的证据 / 依据列表",
    )


class Architecture(BaseModel):
    """架构设计。

    pattern / components / workflow 描述架构本身；key_design 补充关键
    设计决策与权衡；evidence 给出支撑该架构设计的证据 / 依据列表。
    """

    pattern: str = Field(
        default="",
        description="架构模式，允许为空，例如 分层架构 / 微服务 / 事件驱动",
    )
    components: list[str] = Field(
        description="架构组件列表，例如 [API 网关, 消息队列, 缓存]"
    )
    workflow: str = Field(description="工作流程描述，例如 数据如何从入口流转到各组件")
    key_design: str | None = Field(
        default=None,
        description="补充说明：关键设计决策与权衡",
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="支撑该架构设计的证据 / 依据列表",
    )


class KnowledgeProposal(BaseModel):
    """知识提案——用于沉淀「要学习 / 要构建」的知识主题。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200, description="提案标题（必填，长度 ≤ 200）")
    summary: str = Field(min_length=1, description="提案摘要（必填）")
    problem: str = Field(min_length=1, description="要解决的问题（必填）")

    core_features: list[Feature] = Field(
        min_length=1,
        max_length=8,
        description="核心功能，数量 1~8（每项含 description 与 evidence）",
    )

    technologies: list[Technology] = Field(description="技术栈列表")

    architecture: Architecture = Field(description="架构设计")

    learning_points: list[str] = Field(
        min_length=1,
        max_length=8,
        description="学习要点，数量 1~8",
    )
