"""mock 仓库的共享文件内容。

get_file 与 search_code 都基于这一份内容，为的是让两者互相自洽：
search_code 报出 src/demo_project/agent.py 第几行有匹配，get_file 就真的能
读到那一行。否则 LLM 顺着搜索结果去读文件却读不到，mock 就成了自相矛盾的
假数据 —— 而 LLM 据以做决策的正是这些数据。

文件清单与 get_project_structure.MOCK_PATHS 里列出的文件一一对应：
目录结构里出现过的文件，都应该能被 get_file 读到。

下划线开头表示这不是一个 Tool，只是 Tool 之间的共享数据。
"""

from app.tools.get_readme import MOCK_README

MOCK_FILES: dict[str, str] = {
    "README.md": MOCK_README,
    "LICENSE": """MIT License

Copyright (c) 2026 demo-project

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
""",
    "pyproject.toml": """[project]
name = "demo-project"
version = "0.1.0"
description = "一个用于演示 Knowledge Agent 的示例仓库。"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
    "src/demo_project/__init__.py": """from demo_project.agent import Agent

__all__ = ["Agent"]
""",
    "src/demo_project/agent.py": '''"""Agent：按固定顺序调用 Tool，并把产出记录成 Evidence。"""

from demo_project.tools import ToolRegistry


class Agent:
    """一次调查 = 一个实例。"""

    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo
        self.registry = ToolRegistry()
        self.evidence = []

    def run(self):
        """采集证据：先取元数据，再读 README。

        Tool 的返回值由代码转成 Evidence，全程没有 LLM 参与。
        """
        self.evidence.append(self.metadata_evidence())
        self.evidence.append(self.readme_evidence())
        return self.evidence

    def metadata_evidence(self):
        """元数据是结构化数据，序列化后才是完整的事实。"""
        metadata = self.registry.call(
            "get_project_metadata", owner=self.owner, repo=self.repo
        )
        return Evidence.from_metadata(metadata)

    def readme_evidence(self):
        document = self.registry.call("get_readme", owner=self.owner, repo=self.repo)
        return Evidence.from_document(document)
''',
    "src/demo_project/tools.py": '''"""Tool 注册与调用。"""


class ToolRegistry:
    """按名字找到 Tool 并执行。"""

    def __init__(self) -> None:
        self._tools = {}

    def register(self, name: str, function) -> None:
        self._tools[name] = function

    def call(self, name: str, **arguments):
        """调用一个 Tool，返回它的原始结果。

        未注册的名字直接报错，不要让调用方拿到一个来路不明的返回值。
        """
        if name not in self._tools:
            raise KeyError(f"未注册的 Tool: {name}")
        return self._tools[name](**arguments)
''',
    "tests/test_agent.py": '''from demo_project.agent import Agent


def test_采集到两条证据():
    agent = Agent(owner="example", repo="demo-project")

    evidence = agent.run()

    assert len(evidence) == 2
    assert [e.evidence_type for e in evidence] == ["metadata", "readme"]


def test_两次运行互不影响():
    agent = Agent(owner="example", repo="demo-project")

    assert len(agent.run()) == len(agent.run())
''',
}
