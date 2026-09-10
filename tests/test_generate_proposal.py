"""generate_proposal() 相关的测试。

FakeLLM 的草稿是脚本里写死的，所以这里测不出「LLM 归纳得好不好」，
测的是装配关系：代码负责的字段有没有真的由代码给出、LLM 负责的字段有没有
真的进到成品里、失败时有没有明确的出口。

initialize_state() 给的两条 Evidence 是 [1] metadata、[2] readme。
"""

from app.agents.knowledge_agent import KnowledgeAgent
from app.graph.state import KnowledgeProcessState
from app.llm import FakeLLM
from app.llm.client import LLMNotConfiguredError
from app.schemas.knowledge import KnowledgeProposal, ProposalDraft

_FINISH = {"action": "finish"}

_DRAFT = {
    "summary": "一个用来验证知识采集链路的演示项目。",
    "problem": "验证 Evidence 能否被归纳成可落库的知识。",
    "core_features": [
        {"description": "固定采集 metadata 与 README", "evidence_refs": [1, 2]},
    ],
    "technologies": [
        {"name": "Python", "category": "language", "evidence_refs": [1]},
    ],
    "architecture": {
        "pattern": "",
        "components": ["KnowledgeAgent"],
        "workflow": "采集 → 调查 → 生成提案",
        "key_design": None,
        "evidence_refs": [2],
    },
    "learning_points": ["Evidence 由代码生成，不交给 LLM"],
}


def _agent(llm=None) -> KnowledgeAgent:
    return KnowledgeAgent(owner="example", repo="demo-project", llm=llm)


def test_可以正常生成_proposal():
    llm = FakeLLM(_DRAFT)
    agent = _agent(llm)
    state = agent.initialize_state()

    result = agent.generate_proposal(state)

    assert result.status == "analyzing"
    assert result.error is None
    assert result.proposal is not None
    # LLM 负责的字段原样进到成品里
    assert result.proposal.summary == _DRAFT["summary"]
    assert result.proposal.problem == _DRAFT["problem"]
    assert result.proposal.learning_points == _DRAFT["learning_points"]
    assert result.proposal.technologies[0].name == "Python"
    assert result.proposal.architecture.components == ["KnowledgeAgent"]


def test_title_由代码给出而不是_llm():
    # 草稿里根本没有 title —— LLM 没有机会写它
    assert "title" not in ProposalDraft.model_fields

    llm = FakeLLM(_DRAFT)
    agent = _agent(llm)
    result = agent.generate_proposal(agent.initialize_state())

    assert result.proposal.title == "example/demo-project"


def test_生成的_proposal_符合现有_schema():
    llm = FakeLLM(_DRAFT)
    agent = _agent(llm)

    result = agent.generate_proposal(agent.initialize_state())

    assert isinstance(result.proposal, KnowledgeProposal)
    # 能被 schema 重新校验一遍（不是「结构凑合能用」）
    KnowledgeProposal.model_validate(result.proposal.model_dump())


def test_evidence_正文来自_state_而不是_llm():
    llm = FakeLLM(_DRAFT)
    agent = _agent(llm)
    state = agent.initialize_state()

    result = agent.generate_proposal(state)

    # 草稿里只写了编号 [1, 2]，成品里必须是 State 里那两条原文
    feature_evidence = result.proposal.core_features[0].evidence
    assert [e.location for e in feature_evidence] == [
        "https://github.com/example/demo-project",
        "README.md",
    ]
    assert feature_evidence[1].content == state.evidence[1].content
    assert feature_evidence[1].content.startswith("# Demo Project")

    # 同一份 Evidence 可以同时支撑多个字段
    assert result.proposal.technologies[0].evidence[0].location == (
        "https://github.com/example/demo-project"
    )
    assert result.proposal.architecture.evidence[0].location == "README.md"


def test_生成阶段不调用_Tool(monkeypatch):
    from app.agents import knowledge_agent as module

    def _boom(*args, **kwargs):
        raise AssertionError("generate_proposal() 不应该调用 Tool")

    monkeypatch.setattr(module, "call_tool", _boom)

    llm = FakeLLM(_DRAFT)
    agent = _agent(llm)
    state = agent.initialize_state()

    result = agent.generate_proposal(state)

    assert result.proposal is not None
    # Evidence 与 Tool 计数都不受影响 —— 这一阶段只读不写
    assert result.evidence == state.evidence
    assert result.tool_call_count == state.tool_call_count == 0


def test_引用不存在的编号会落成_failed():
    draft = {
        **_DRAFT,
        "core_features": [{"description": "x", "evidence_refs": [99]}],
    }
    agent = _agent(FakeLLM(draft))

    result = agent.generate_proposal(agent.initialize_state())

    assert result.status == "failed"
    assert result.proposal is None
    assert "[99]" in result.error


def test_llm_输出不合法会落成_failed():
    draft = {**_DRAFT, "core_features": []}  # 违反 min_length=1
    agent = _agent(FakeLLM(draft))

    result = agent.generate_proposal(agent.initialize_state())

    assert result.status == "failed"
    assert result.proposal is None
    assert result.error.startswith("LLM 输出不符合 ProposalDraft")


def test_没有_evidence_时不调用_llm_直接落成_failed():
    # 空脚本：只要 LLM 被调用一次，FakeLLM 就会报错
    llm = FakeLLM()
    agent = _agent(llm)
    state = agent.initialize_state().model_copy(update={"evidence": []})

    result = agent.generate_proposal(state)

    assert result.status == "failed"
    assert result.proposal is None
    assert "没有 Evidence" in result.error
    assert llm.calls == []


def test_传入的_state_不会被修改():
    llm = FakeLLM(_DRAFT)
    agent = _agent(llm)
    state = agent.initialize_state()

    result = agent.generate_proposal(state)

    assert result is not state
    assert state.proposal is None
    assert state.status == "collecting"
    assert state.error is None


def test_没配_llm_时报错():
    agent = _agent()  # llm=None
    state = agent.initialize_state()

    try:
        agent.generate_proposal(state)
    except LLMNotConfiguredError:
        pass
    else:
        raise AssertionError("应当抛出 LLMNotConfiguredError")


def test_run_的最终_state_里有_proposal():
    llm = FakeLLM(_FINISH, _DRAFT)
    agent = _agent(llm)

    result = agent.run()

    assert isinstance(result, KnowledgeProcessState)
    assert result.proposal is not None
    assert result.status == "analyzing"
    assert [e.evidence_type for e in result.evidence] == ["metadata", "readme"]
    # 两次调用：investigate 的决策一次、generate_proposal 一次
    assert len(llm.calls) == 2
    # 两条提示词不共用 —— 提案阶段是独立的 prompt
    assert llm.calls[0]["system"] != llm.calls[1]["system"]


def test_run_把工具产出的_evidence_也带进提案阶段():
    tool_call = {
        "action": "tool_call",
        "tool_name": "get_project_structure",
        "tool_arguments": {"owner": "example", "repo": "demo-project"},
    }
    # 草稿引用了第 3 条，也就是 get_project_structure 补进来的那条
    draft = {
        **_DRAFT,
        "core_features": [{"description": "x", "evidence_refs": [3]}],
    }
    agent = _agent(FakeLLM(tool_call, _FINISH, draft))

    result = agent.run()

    assert result.tool_call_count == 1
    assert result.proposal.core_features[0].evidence[0].evidence_type == "structure"
