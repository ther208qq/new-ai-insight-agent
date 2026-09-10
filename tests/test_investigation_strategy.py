"""调查策略相关的测试。

先说清楚这一组测的是什么：FakeLLM 的决策是**脚本里写死的**，
所以它证明不了「LLM 能不能根据 Evidence 选出合理的 Tool」——
脚本选什么就断言什么。要验证模型的判断力，只能用真实 LLM。

这里测的是：提示词描述的那条三步调查策略（结构 → 搜索定位 → 读文件），
在执行层已经能完整走通，并且每一步的产出都真的变成了下一轮的 Evidence。
"""

from app.agents.knowledge_agent import KnowledgeAgent
from app.llm import FakeLLM

_FINISH = {"action": "finish"}


def _tool_call(tool_name: str, **arguments) -> dict:
    return {
        "action": "tool_call",
        "tool_name": tool_name,
        "tool_arguments": arguments or {"owner": "example", "repo": "demo-project"},
    }


def _agent(llm) -> KnowledgeAgent:
    return KnowledgeAgent(owner="example", repo="demo-project", llm=llm)


def test_信息已足够时_一次_tool_都不调用直接_finish():
    """「已经够了就直接 finish」这条行为。

    脚本里只放 finish，FakeLLM 多被调用一次都会报错，
    所以这个测试同时钉住了「没有多余调用」。
    """
    llm = FakeLLM(_FINISH)
    agent = _agent(llm)

    result = agent.investigate(agent.run())

    assert len(llm.calls) == 1
    assert result.tool_call_count == 0
    assert [e.evidence_type for e in result.evidence] == ["metadata", "readme"]


def test_有缺口时先补目录结构再_finish():
    """「先看整体组织，再判断够不够」这条策略的 happy path。"""
    llm = FakeLLM(_tool_call("get_project_structure"), _FINISH)
    agent = _agent(llm)

    result = agent.investigate(agent.run())

    assert [e.evidence_type for e in result.evidence] == [
        "metadata",
        "readme",
        "structure",
    ]
    assert result.tool_call_count == 1


def test_三步调查策略可以完整走通():
    """提示词里的完整策略：目录 → 搜索定位 → 读文件 → finish。

    上一版这个测试断言的是「走到第二步就中断」（get_file / search_code
    当时还不能执行）。执行层补齐后它被改成了成功用例。
    """
    llm = FakeLLM(
        _tool_call("get_project_structure"),
        _tool_call("search_code", query="Evidence"),
        _tool_call("get_file", path="src/demo_project/agent.py"),
        _FINISH,
    )
    agent = _agent(llm)

    result = agent.investigate(agent.run())

    assert [e.evidence_type for e in result.evidence] == [
        "metadata",
        "readme",
        "structure",
        "search",
        "code",
    ]
    assert result.tool_call_count == 3


def test_搜索定位到文件后_get_file_能读到搜索结果里的行():
    """mock 数据必须自洽：搜到的行，读文件时真的存在。

    否则 LLM 会顺着搜索结果去读文件却读不到，据以决策的就是矛盾数据。
    """
    llm = FakeLLM(
        _tool_call("search_code", query="Evidence"),
        _tool_call("get_file", path="src/demo_project/agent.py"),
        _FINISH,
    )
    agent = _agent(llm)

    result = agent.investigate(agent.run())

    search_evidence, code_evidence = result.evidence[-2], result.evidence[-1]

    # 在搜索结果里挑出属于 agent.py 的那条（content 是 "path:行号: 内容"）
    match = next(
        line
        for line in search_evidence.content.splitlines()
        if line.startswith("src/demo_project/agent.py:")
    )
    # 行格式是 "path:行号: 内容"，path 与行号之间是 ":"，行号与内容之间才是 ": "
    _, _, matched_text = match.partition(": ")

    # 搜到的那行，确实出现在 get_file 读回的正文里
    assert matched_text in code_evidence.content


def test_读不存在的文件会中断():
    """get_file 路径不存在时抛 FileNotFoundError，整轮中断。

    「Tool 失败自动恢复」尚未实现，所以这是当前的预期行为。
    """
    llm = FakeLLM(_tool_call("get_file", path="不存在的文件.py"), _FINISH)
    agent = _agent(llm)

    try:
        agent.investigate(agent.run())
    except FileNotFoundError as error:
        assert "文件不存在" in str(error)
    else:
        raise AssertionError("应当抛出 FileNotFoundError")


def test_搜不到结果不是错误_而是一条有效证据():
    """搜索空结果要能让 LLM 看出来「搜过了，没有」。"""
    llm = FakeLLM(_tool_call("search_code", query="zzz不存在zzz"), _FINISH)
    agent = _agent(llm)

    result = agent.investigate(agent.run())

    assert result.evidence[-1].evidence_type == "search"
    assert result.evidence[-1].location == "search:zzz不存在zzz"
    assert result.evidence[-1].content == "（没有匹配到任何内容）"
