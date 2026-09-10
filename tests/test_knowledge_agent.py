from app.agents.knowledge_agent import KnowledgeAgent
from app.graph.state import KnowledgeProcessState


def test_运行后_state_里同时有_metadata_和_readme_两条_evidence():
    state = KnowledgeAgent(owner="example", repo="demo-project").run()

    assert isinstance(state, KnowledgeProcessState)
    assert len(state.evidence) == 2
    assert [e.evidence_type for e in state.evidence] == ["metadata", "readme"]
    assert [e.location for e in state.evidence] == [
        "https://github.com/example/demo-project",
        "README.md",
    ]
    # content 来自 Tool 的原始返回
    assert '"name": "demo-project"' in state.evidence[0].content
    assert state.evidence[1].content.startswith("# Demo Project")


def test_source_由_owner_和_repo_组成_且每次运行互不影响():
    agent = KnowledgeAgent(owner="example", repo="demo-project")

    first = agent.run()
    second = agent.run()

    assert first.source.url == "https://github.com/example/demo-project"
    assert first.source.type == "github"
    assert first.process_id != second.process_id
    # 第二次运行不会叠加到第一次的 evidence 上
    assert len(first.evidence) == len(second.evidence) == 2
