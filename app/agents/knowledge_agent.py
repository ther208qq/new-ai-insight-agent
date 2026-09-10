"""Knowledge Agent 的最小版本。

给定一个 GitHub 项目的 owner / repo，固定完成：

    get_project_metadata ─┐
                          ├→ Evidence → State.evidence
    get_readme ───────────┘

调什么、按什么顺序，目前全部写死在 run() 里 —— 还没有 LLM、没有
Tool Calling Loop、没有 Harness、没有 Reflection。等这些接进来之后，
这条固定流程会变成「由 LLM 决定下一步调哪个 Tool」的循环。
"""

from uuid import uuid4

from app.graph.evidence import (
    document_to_evidence,
    metadata_to_evidence,
    record_evidence,
)
from app.graph.state import KnowledgeProcessState, Source
from app.tools.get_project_metadata import get_project_metadata
from app.tools.get_readme import get_readme


class KnowledgeAgent:
    """一次运行 = 一个实例。"""

    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo
        self.source = Source(
            url=f"https://github.com/{owner}/{repo}",
            type="github",
        )

    def run(self) -> KnowledgeProcessState:
        """收集证据，返回更新后的 State。

        每调用一次都会新建一个 State（process_id 是新的），
        所以两次 run() 之间不会互相污染。
        """
        state = KnowledgeProcessState(
            process_id=uuid4().hex,
            source=self.source,
            status="collecting",
        )

        # 两个 Tool 的返回值由代码转成 Evidence —— 全程没有 LLM 参与
        state = record_evidence(
            state,
            metadata_to_evidence(get_project_metadata(self.owner, self.repo)),
            document_to_evidence(get_readme(self.owner, self.repo)),
        )

        return state
