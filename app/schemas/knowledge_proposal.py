"""知识提案 (KnowledgeProposal) 相关的 Pydantic schema。

本模块定义 LLM 生成「知识提案」时输出的结构化数据格式，
作为 LLM 世界与传统后端世界之间的边界 (见 CHANGELOG.md 的模块职责)。
"""

from pydantic import BaseModel, ConfigDict, Field


class Technology(BaseModel):
    """单项技术栈。

    evidence 是对 name / category 的补充说明：
    为什么选择这项技术、有什么依据支撑。
    """

    name: str = Field(description="技术名称，例如 FastAPI、PostgreSQL、Redis")
    category: str = Field(description="技术分类，例如 后端框架 / 数据库 / 消息队列 / 部署")
    evidence: str | None = Field(
        default=None,
        description="补充说明：选择该技术的依据 / 证据",
    )


class Architecture(BaseModel):
    """架构设计。

    key_design 是对 pattern / components / workflow 的补充说明：
    关键设计决策与权衡。
    """

    pattern: str = Field(description="架构模式，例如 分层架构 / 微服务 / 事件驱动")
    components: list[str] = Field(
        description="架构组件列表，例如 [API 网关, 消息队列, 缓存]"
    )
    workflow: str = Field(description="工作流程描述，例如 数据如何从入口流转到各组件")
    key_design: str | None = Field(
        default=None,
        description="补充说明：关键设计决策与权衡",
    )


class KnowledgeProposal(BaseModel):
    """知识提案——用于沉淀「要学习 / 要构建」的知识主题。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, description="提案标题（必填）")
    summary: str = Field(min_length=1, description="提案摘要（必填）")
    problem: str = Field(min_length=1, description="要解决的问题（必填）")

    core_features: list[str] = Field(
        min_length=1,
        max_length=8,
        description="核心功能，数量 1~8",
    )

    technologies: list[Technology] = Field(description="技术栈列表")

    architecture: Architecture = Field(description="架构设计")

    learning_points: list[str] = Field(
        min_length=1,
        max_length=8,
        description="学习要点，数量 1~8",
    )
