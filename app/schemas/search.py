"""代码搜索结果 (SearchResult) 的 Pydantic schema。

SearchResult 是 Tool 在仓库代码里搜关键词时返回的结构化表示，
作为 Tool 世界与后端世界之间的边界。
"""

from pydantic import BaseModel, ConfigDict, Field


class CodeMatch(BaseModel):
    """一条代码匹配。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="匹配所在的文件路径")
    line_number: int = Field(description="匹配所在行号，从 1 开始")
    line: str = Field(description="匹配到的那一行内容")


class SearchResult(BaseModel):
    """一次代码搜索的结果。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="搜索的关键词")
    matches: list[CodeMatch] = Field(
        default_factory=list,
        description="匹配列表；没有匹配时为空列表（空结果是正常结果，不是错误）",
    )
    truncated: bool = Field(
        default=False,
        description="匹配列表是否因为数量限制被截断",
    )
