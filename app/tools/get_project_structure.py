"""获取仓库目录结构的 Tool。

当前返回固定的模拟结构，不访问 GitHub API。
owner / repo 先保留在签名里，等接入真实 API 时才会用到。
"""

from app.schemas.structure import ProjectStructure

MOCK_PATHS = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "src/",
    "src/demo_project/",
    "src/demo_project/__init__.py",
    "src/demo_project/agent.py",
    "src/demo_project/tools.py",
    "tests/",
    "tests/test_agent.py",
]


def get_project_structure(owner: str, repo: str) -> ProjectStructure:
    """返回一个仓库的目录结构。"""
    return ProjectStructure(
        paths=list(MOCK_PATHS),
        truncated=False,
    )
