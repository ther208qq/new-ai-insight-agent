"""项目元数据 (ProjectMetadata) 的 Pydantic schema。

ProjectMetadata 是 Tool 从外部数据源（GitHub 等）取回的「项目画像」的
结构化表示，作为 Tool 世界与后端世界之间的边界。
"""

from pydantic import BaseModel, ConfigDict, Field


class ProjectMetadata(BaseModel):
    """一个代码仓库的基础元数据。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="项目名，例如 fastapi")
    description: str = Field(description="项目简介，对应仓库的 description")
    url: str = Field(description="项目地址，例如 https://github.com/tiangolo/fastapi")
    language: str | None = Field(description="主要语言，无法判断时为 None")
    stars: int = Field(description="star 数")
    topics: list[str] = Field(description="仓库 topics 标签")
