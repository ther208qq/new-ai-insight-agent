from app.agents.knowledge_agent import KnowledgeAgent
from app.graph.state import KnowledgeProcessState


def test_初始化后_state_里同时有_metadata_和_readme_两条_evidence():
    # run() 现在还要走 investigate + generate_proposal（都要 LLM），
    # 只想验证采集这一步，所以调 initialize_state()
    state = KnowledgeAgent(owner="example", repo="demo-project").initialize_state()

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

    first = agent.initialize_state()
    second = agent.initialize_state()

    assert first.source.url == "https://github.com/example/demo-project"
    assert first.source.type == "github"
    assert first.process_id != second.process_id
    # 第二次运行不会叠加到第一次的 evidence 上
    assert len(first.evidence) == len(second.evidence) == 2
