"""项目结构 (ProjectStructure) 的 Pydantic schema。

ProjectStructure 是 Tool 取回「仓库目录结构」时的结构化表示，
作为 Tool 世界与后端世界之间的边界。

paths 里放的是仓库根目录下的路径（目录和文件都算），不在这里判断
哪条是目录、哪条是文件 —— 那属于分析，不是采集。
"""

from pydantic import BaseModel, ConfigDict, Field


class ProjectStructure(BaseModel):
    """一个代码仓库的目录结构。"""

    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(description="仓库中的路径列表，例如 [src, src/main.py]")
    truncated: bool = Field(
        default=False,
        description="路径列表是否因为数量限制被截断",
    )
