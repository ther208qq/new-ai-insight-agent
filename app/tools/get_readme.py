"""获取仓库 README 的 Tool。

当前返回固定的模拟 README，不访问 GitHub API。
owner / repo 先保留在签名里，等接入真实 API 时才会用到。
"""

from app.schemas.document import DocumentContent

MOCK_README = """# Demo Project

一个用于演示 Knowledge Agent 的示例仓库。

## 特性

- 读取 GitHub 仓库的 README 与目录结构
- 按需读取具体文件的内容
- 自动把工具返回的内容沉淀为 Evidence

## 安装

```bash
pip install demo-project
```

## 使用

```python
from demo_project import run

run(owner="example", repo="demo-project")
```

## 架构

入口 -> 工具调用循环 -> 知识提案

## License

MIT
"""


def get_readme(owner: str, repo: str) -> DocumentContent:
    """返回仓库 README 的内容。"""
    return DocumentContent(
        path="README.md",
        content=MOCK_README,
        truncated=False,
    )
