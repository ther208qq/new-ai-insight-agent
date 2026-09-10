"""文档内容 (DocumentContent) 的 Pydantic schema。

DocumentContent 是 Tool 取回「一份文本文件」时的统一表示：
README、源码文件、文档都复用它，作为 Tool 世界与后端世界之间的边界。
"""

from pydantic import BaseModel, ConfigDict, Field


class DocumentContent(BaseModel):
    """一份文本文件的内容。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="文件路径，例如 README.md")
    content: str = Field(description="文件的文本内容")
    truncated: bool = Field(description="内容是否因为长度限制被截断")
