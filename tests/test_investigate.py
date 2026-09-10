from app.agents.knowledge_agent import MAX_TOOL_CALLS, KnowledgeAgent
from app.llm import FakeLLM

_TOOL_CALL = {
    "action": "tool_call",
    "tool_name": "get_project_structure",
    "tool_arguments": {"owner": "example", "repo": "demo-project"},
}
_FINISH = {"action": "finish"}


def _agent(llm) -> KnowledgeAgent:
    return KnowledgeAgent(owner="example", repo="demo-project", llm=llm)


def test_一轮_tool_call_后_finish_就结束():
    llm = FakeLLM(_TOOL_CALL, _FINISH)
    agent = _agent(llm)

    state = agent.initialize_state()
    result = agent.investigate(state)

    # 决策了两次：一次选 Tool，一次说够了
    assert len(llm.calls) == 2

    # execute() 拿到的 Evidence 真的进了 State
    assert [e.evidence_type for e in result.evidence] == [
        "metadata",
        "readme",
        "structure",
    ]
    assert "src/demo_project/agent.py" in result.evidence[-1].content
    assert result.tool_call_count == 1


def test_传入的_state_不会被修改():
    llm = FakeLLM(_TOOL_CALL, _FINISH)
    agent = _agent(llm)
    state = agent.initialize_state()

    result = agent.investigate(state)

    assert result is not state
    assert len(state.evidence) == 2  # 原 state 只有 run() 采的那两条
    assert state.tool_call_count == 0
    assert len(result.evidence) == 3


def test_第二轮决策能看到上一轮新增的_evidence():
    llm = FakeLLM(_TOOL_CALL, _FINISH)
    agent = _agent(llm)

    agent.investigate(agent.initialize_state())

    # 第二次 decide 的 Context 里必须已经含有 get_project_structure 的产出
    second_context = llm.calls[1]["user"]
    assert "structure" in second_context
    assert "src/demo_project/agent.py" in second_context


def test_第一次就_finish_则一次_tool_都不执行():
    llm = FakeLLM(_FINISH)
    agent = _agent(llm)

    result = agent.investigate(agent.initialize_state())

    assert len(llm.calls) == 1
    assert result.tool_call_count == 0
    assert len(result.evidence) == 2


def test_反复_tool_call_会在达到上限后停止_不会无限循环():
    # 故意给远超上限的脚本：循环若是靠「脚本用完」才停的，这个测试会失败
    llm = FakeLLM(*([_TOOL_CALL] * (MAX_TOOL_CALLS + 3)))
    agent = _agent(llm)

    result = agent.investigate(agent.initialize_state())

    assert result.tool_call_count == MAX_TOOL_CALLS
    assert len(llm.calls) == MAX_TOOL_CALLS
    assert len(result.evidence) == 2 + MAX_TOOL_CALLS
    # 上限是兜底，不是完成
    assert result.status == "collecting"


def test_state_已在上限时直接返回_不调用_llm():
    # 空脚本：只要 decide() 被调一次，FakeLLM 就会报错
    llm = FakeLLM()
    agent = _agent(llm)
    state = agent.initialize_state().model_copy(update={"tool_call_count": MAX_TOOL_CALLS})

    result = agent.investigate(state)

    assert llm.calls == []
    assert len(result.evidence) == 2


def test_可以接着已有计数继续调查():
    llm = FakeLLM(_TOOL_CALL, _FINISH)
    agent = _agent(llm)
    state = agent.initialize_state().model_copy(update={"tool_call_count": MAX_TOOL_CALLS - 1})

    result = agent.investigate(state)

    # 只剩一次额度，用完就停 —— 不会拿到 finish 的那次决策
    assert result.tool_call_count == MAX_TOOL_CALLS
    assert len(llm.calls) == 1
