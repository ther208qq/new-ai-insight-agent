from app.graph.evidence import (
    document_to_evidence,
    metadata_to_evidence,
    record_evidence,
)
from app.graph.state import KnowledgeProcessState, Source
from app.schemas.document import DocumentContent
from app.schemas.evidence import Evidence
from app.schemas.project import ProjectMetadata


def make_state() -> KnowledgeProcessState:
    return KnowledgeProcessState(
        process_id="process-1",
        source=Source(url="https://github.com/example/demo-project", type="github"),
        status="collecting",
    )


def make_metadata() -> ProjectMetadata:
    """直接构造：元数据怎么取回来是 get_project_metadata 的事，这里只测它如何变 Evidence。"""
    return ProjectMetadata(
        name="demo-project",
        description="一个用于演示 Knowledge Agent 的示例仓库。",
        url="https://github.com/example/demo-project",
        language="Python",
        stars=128,
        topics=["demo", "agent", "llm"],
    )


def test_metadata_能生成_evidence():
    metadata = make_metadata()

    evidence = metadata_to_evidence(metadata)

    assert isinstance(evidence, Evidence)
    assert evidence.source == "github"
    assert evidence.location == "https://github.com/example/demo-project"
    assert evidence.evidence_type == "metadata"
    # content 是元数据的原始 JSON，没有被概括或改写
    assert '"name": "demo-project"' in evidence.content
    assert '"stars": 128' in evidence.content


def make_readme() -> DocumentContent:
    """同上：README 怎么取回来是 get_readme 的事。"""
    return DocumentContent(
        path="README.md",
        content="# Demo Project\n\n一个用于演示 Knowledge Agent 的示例仓库。\n",
        truncated=False,
    )


def test_readme_能生成_evidence():
    readme = make_readme()

    evidence = document_to_evidence(readme)

    assert isinstance(evidence, Evidence)
    assert evidence.source == "github"
    assert evidence.location == "README.md"
    assert evidence.evidence_type == "readme"
    # content 逐字来自 DocumentContent，没有任何加工
    assert evidence.content == readme.content


def test_非_readme_文件生成_code_evidence():
    document = DocumentContent(
        path="app/workflow.py",
        content="def run(): ...",
        truncated=False,
    )

    assert document_to_evidence(document).evidence_type == "code"


def test_类型可以覆盖():
    document = DocumentContent(path="README.md", content="x", truncated=False)

    evidence = document_to_evidence(document, evidence_type="documentation")

    assert evidence.evidence_type == "documentation"


def test_两条_evidence_都能进入_state():
    state = make_state()

    state = record_evidence(
        state,
        metadata_to_evidence(make_metadata()),
        document_to_evidence(make_readme()),
    )

    assert len(state.evidence) == 2
    assert [e.evidence_type for e in state.evidence] == ["metadata", "readme"]
    assert [e.location for e in state.evidence] == [
        "https://github.com/example/demo-project",
        "README.md",
    ]


def test_record_evidence_不修改传入的_state():
    state = make_state()
    before = state.model_dump()

    record_evidence(state, metadata_to_evidence(make_metadata()))

    assert state.model_dump() == before


def test_可以连续追加():
    state = make_state()

    state = record_evidence(state, metadata_to_evidence(make_metadata()))
    state = record_evidence(state, document_to_evidence(make_readme()))

    assert [e.evidence_type for e in state.evidence] == ["metadata", "readme"]
