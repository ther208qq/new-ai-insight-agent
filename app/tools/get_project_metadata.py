"""获取仓库基础元数据的 Tool。

当前返回固定的模拟数据，不访问 GitHub API。
owner / repo 先保留在签名里，等接入真实 API 时才会用到。
"""

from app.schemas.project import ProjectMetadata


def get_project_metadata(owner: str, repo: str) -> ProjectMetadata:
    """返回一个仓库的基础元数据。"""
    return ProjectMetadata(
        name="demo-project",
        description="一个用于演示 Knowledge Agent 的示例仓库。",
        url="https://github.com/example/demo-project",
        language="Python",
        stars=128,
        topics=["demo", "agent", "llm"],
    )
