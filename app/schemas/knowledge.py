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


# ---------------------------------------------------------------------------
# LLM 侧草稿 (ProposalDraft)
#
# 上面几个是最终落库的结构；下面几个是 LLM 的输出结构，只含「必须由 LLM 判断」
# 的字段。差别只有两处，都是「代码能确定、所以不该让 LLM 写」的部分：
#
#   title        最终结构里有，草稿里没有 —— 代码用 owner/repo 直接填。
#   evidence     最终结构里是 list[Evidence]（含正文），草稿里是 list[int] 编号 ——
#                正文就在 State 里，代码按编号取原文回填。
#
# 让 LLM 直接输出 KnowledgeProposal 是行不通的：那个 schema 要求它把证据正文
# 再写一遍，而 evidence.py 的约定是「Evidence 必须由代码生成」。草稿不是第二套
# Proposal —— 落库/反思/关系用的仍然只有 KnowledgeProposal 一个。
# ---------------------------------------------------------------------------


class DraftFeature(BaseModel):
    """core_features 的草稿：evidence 用编号引用，正文由代码回填。"""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="核心功能描述")
    evidence_refs: list[int] = Field(
        default_factory=list,
        description="支撑该功能的 Evidence 编号（Context 里的 [n]）",
    )


class DraftTechnology(BaseModel):
    """technologies 的草稿：evidence 用编号引用，正文由代码回填。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="技术名称，例如 FastAPI、PostgreSQL、Redis")
    category: TechnologyCategory = Field(
        description=(
            "技术分类（固定枚举）：framework / language / database / "
            "infrastructure / library / model / other"
        )
    )
    evidence_refs: list[int] = Field(
        default_factory=list,
        description="支撑该选型的 Evidence 编号（Context 里的 [n]）",
    )


class DraftArchitecture(BaseModel):
    """architecture 的草稿：evidence 用编号引用，正文由代码回填。"""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(
        default="",
        description="架构模式，允许为空，例如 分层架构 / 微服务 / 事件驱动",
    )
    components: list[str] = Field(description="架构组件列表，例如 [API 网关, 消息队列, 缓存]")
    workflow: str = Field(description="工作流程描述，例如 数据如何从入口流转到各组件")
    key_design: str | None = Field(
        default=None,
        description="补充说明：关键设计决策与权衡",
    )
    evidence_refs: list[int] = Field(
        default_factory=list,
        description="支撑该架构设计的 Evidence 编号（Context 里的 [n]）",
    )


class ProposalDraft(BaseModel):
    """LLM 输出的知识提案草稿。

    数值约束与 KnowledgeProposal 保持一致，让校验在 LLM 边界就发生 ——
    而不是拖到代码拼装成品时才炸。
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, description="提案摘要（必填）")
    problem: str = Field(min_length=1, description="要解决的问题（必填）")

    core_features: list[DraftFeature] = Field(
        min_length=1,
        max_length=8,
        description="核心功能，数量 1~8",
    )

    technologies: list[DraftTechnology] = Field(description="技术栈列表")

    architecture: DraftArchitecture = Field(description="架构设计")

    learning_points: list[str] = Field(
        min_length=1,
        max_length=8,
        description="学习要点，数量 1~8",
    )
