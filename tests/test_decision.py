import pytest
from pydantic import ValidationError

from app.schemas.decision import AgentDecision


def test_工具调用决策_携带_tool_name_和_tool_arguments():
    decision = AgentDecision(
        action="tool_call",
        tool_name="get_readme",
        tool_arguments={"owner": "example", "repo": "demo-project"},
    )

    assert decision.action == "tool_call"
    assert decision.tool_name == "get_readme"
    assert decision.tool_arguments == {"owner": "example", "repo": "demo-project"}


def test_结束决策_tool_name_和_tool_arguments_均为_None():
    decision = AgentDecision(action="finish")

    assert decision.action == "finish"
    assert decision.tool_name is None
    assert decision.tool_arguments is None


def test_也可以显式传入_None():
    decision = AgentDecision(action="finish", tool_name=None, tool_arguments=None)

    assert decision.tool_name is None
    assert decision.tool_arguments is None


def test_action_只允许_tool_call_和_finish():
    with pytest.raises(ValidationError):
        AgentDecision(action="think")


def test_不认识的字段会被拒绝():
    with pytest.raises(ValidationError):
        AgentDecision(action="finish", reason="想太多")
