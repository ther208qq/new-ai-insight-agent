import pytest

from app.agents.knowledge_agent import KnowledgeAgent, NotAToolCallError
from app.schemas.decision import AgentDecision
from app.tools.registry import UnsupportedToolError


def _agent() -> KnowledgeAgent:
    return KnowledgeAgent(owner="example", repo="demo-project")


def _tool_call(tool_name="get_project_structure", tool_arguments=None):
    return AgentDecision(
        action="tool_call",
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )


def test_agent_decision_到_tool_到_evidence_到_state():
    agent = _agent()
    state = agent.initialize_state()
    before = len(state.evidence)

    decision = _tool_call(tool_arguments={"owner": "example", "repo": "demo-project"})
    new_state = agent.execute(state, decision)

    # Evidence 成功进入 State
    assert len(new_state.evidence) == before + 1

    evidence = new_state.evidence[-1]
    assert evidence.evidence_type == "structure"
    assert evidence.source == "github"
    assert evidence.location == "."
    # content 就是 Tool 返回的目录结构
    assert "src/demo_project/agent.py" in evidence.content
    assert "tests/test_agent.py" in evidence.content


def test_执行不修改传入的_state():
    agent = _agent()
    state = agent.initialize_state()

    agent.execute(state, _tool_call())

    assert len(state.evidence) == 2  # 原 state 不受影响


def test_llm_给的_owner_repo_被当前仓库覆盖():
    agent = _agent()
    decision = _tool_call(tool_arguments={"owner": "别人", "repo": "别的仓库"})

    # Tool 是按当前 Agent 的 owner/repo 去取的，LLM 填的值不生效
    new_state = agent.execute(agent.initialize_state(), decision)

    assert new_state.evidence[-1].location == "."


def test_不支持的_tool_会明确报错():
    agent = _agent()

    # search_code 曾经是不可执行的例子，现在已接进执行层。
    # 换成一个确实不在 ALLOWED_TOOLS 里、但对 LLM 可见的名字。
    with pytest.raises(UnsupportedToolError, match="不支持的 Tool"):
        agent.execute(agent.initialize_state(), _tool_call(tool_name="get_project_metadata"))


def test_编造的_tool_名也会被拒绝():
    agent = _agent()

    with pytest.raises(UnsupportedToolError, match="不支持的 Tool"):
        agent.execute(agent.initialize_state(), _tool_call(tool_name="totally_made_up"))


def test_多传了参数会报错():
    agent = _agent()

    with pytest.raises(UnsupportedToolError, match="不接受参数"):
        agent.execute(agent.initialize_state(), _tool_call(tool_arguments={"depth": 3}))


def test_finish_决策不会被_execute_执行():
    agent = _agent()

    with pytest.raises(NotAToolCallError):
        agent.execute(agent.initialize_state(), AgentDecision(action="finish"))


def test_tool_call_但缺_tool_name_会报错():
    agent = _agent()

    with pytest.raises(NotAToolCallError):
        agent.execute(agent.initialize_state(), AgentDecision(action="tool_call"))
