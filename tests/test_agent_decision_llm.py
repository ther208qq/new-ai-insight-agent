import pytest

from app.agents.knowledge_agent import KnowledgeAgent
from app.llm import FakeLLM, LLMNotConfiguredError
from app.schemas.decision import AgentDecision


def _agent(llm=None) -> KnowledgeAgent:
    return KnowledgeAgent(owner="example", repo="demo-project", llm=llm)


def test_state_到_llm_到_agent_decision_这条链路能跑通():
    # LLM 看到「只有 metadata + readme」，认为还不够，指名要目录结构
    llm = FakeLLM(
        {
            "action": "tool_call",
            "tool_name": "get_project_structure",
            "tool_arguments": {"owner": "example", "repo": "demo-project"},
        }
    )
    agent = _agent(llm)

    state = agent.run()
    decision = agent.decide(state)

    assert isinstance(decision, AgentDecision)
    assert decision.action == "tool_call"
    assert decision.tool_name == "get_project_structure"
    assert decision.tool_arguments == {"owner": "example", "repo": "demo-project"}


def test_送进_llm_的_context_就是当前_state_里的_evidence():
    llm = FakeLLM({"action": "finish"})
    agent = _agent(llm)

    state = agent.run()
    agent.decide(state)

    prompt = llm.calls[0]["user"]
    # Context 由 State 的 evidence 渲染而来 —— 两条 Evidence 都在
    assert len(llm.calls) == 1
    assert '"name": "demo-project"' in prompt  # metadata 那条
    assert "# Demo Project" in prompt  # readme 那条
    assert "https://github.com/example/demo-project" in prompt


def test_llm_也可以返回_finish():
    agent = _agent(FakeLLM({"action": "finish"}))

    decision = agent.decide(agent.run())

    assert decision.action == "finish"
    assert decision.tool_name is None
    assert decision.tool_arguments is None


def test_llm_返回的决策必须符合_agent_decision_结构():
    # 模型吐 JSON 文本也走同一条校验路径
    llm = FakeLLM('{"action": "tool_call", "tool_name": "get_file"}')

    decision = _agent(llm).decide(_agent().run())

    assert decision.tool_name == "get_file"


def test_llm_返回了_schema_之外的动作会被拒绝():
    agent = _agent(FakeLLM({"action": "think"}))

    with pytest.raises(Exception):
        agent.decide(agent.run())


def test_没有配置_llm_时_采集仍然可用_只有决策报错():
    agent = _agent()

    state = agent.run()
    assert len(state.evidence) == 2

    with pytest.raises(LLMNotConfiguredError):
        agent.decide(state)
