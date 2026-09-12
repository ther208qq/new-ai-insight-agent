"""graph/context 里 Evidence → Context 的截断策略。

只测这一段：单条上限（MAX_EVIDENCE_CHARS）、整段预算（MAX_CONTEXT_CHARS），
以及预算不够时排在后面的 Evidence 会不会整块消失。Proposal / Reflection 两段的
渲染与顺序在 test_reflection.py，截断记在哪一档日志在 test_logging.py。

纯函数，无网络：只构造 State 调 build_context。
"""

from app.graph.context import (
    MAX_CONTEXT_CHARS,
    MAX_EVIDENCE_CHARS,
    build_context,
)
from app.graph.state import KnowledgeProcessState, Source
from app.schemas.evidence import Evidence


def _state(*evidences: Evidence) -> KnowledgeProcessState:
    return KnowledgeProcessState(
        process_id="process-1",
        source=Source(url="https://github.com/o/r", type="github"),
        evidence=list(evidences),
        status="collecting",
    )


def _evidence(index: int, *, chars: int, evidence_type: str = "code") -> Evidence:
    """第 index 条 Evidence，正文是 chars 个 x —— 长度可数，断言才写得死。"""
    return Evidence(
        source="github",
        location=f"src/f{index}.py",
        content="x" * chars,
        evidence_type=evidence_type,
    )


def _full(*counts: int) -> list[Evidence]:
    return [_evidence(i, chars=chars) for i, chars in enumerate(counts, start=1)]


def test_没超预算时所有_evidence_正文都完整给出():
    evidences = _full(100, 500, 2000)

    text = build_context(_state(*evidences))

    for item in evidences:
        assert item.content in text
    assert text.count("### ") == len(evidences)
    assert "已截断" not in text
    assert "预算不足" not in text


def test_单条超长时只截这一条的正文_条目本身还在():
    text = build_context(_state(_evidence(1, chars=MAX_EVIDENCE_CHARS * 3)))

    assert "### [1] code" in text
    assert "- source: github" in text
    assert "- location: src/f1.py" in text
    # 正文砍到单条上限，并且说了自己被截断
    assert text.count("x") == MAX_EVIDENCE_CHARS
    assert "已截断" in text


def test_整段超预算时后面的_evidence_不会整个消失():
    evidences = _full(*[MAX_EVIDENCE_CHARS * 2] * 6)

    text = build_context(_state(*evidences))

    # 这是本次修改的核心：正文可以不给，但每条都得让 LLM 知道它存在
    for index in range(1, len(evidences) + 1):
        assert f"### [{index}] code" in text
        assert f"- location: src/f{index}.py" in text


def test_预算不足的_evidence_保留元信息和明确说明():
    text = build_context(_state(*_full(*[MAX_EVIDENCE_CHARS * 2] * 6)))

    # 整条只剩「编号 + 类型 + 出处 + 一句说明」，正文一个字符都不塞 ——
    # 它占的额度要留给后面可能还有的证据
    assert text.split("### [6] code")[1].strip() == (
        "- source: github\n"
        "- location: src/f6.py\n"
        "- content:\n"
        "（正文未展示：Context 预算不足）"
    )


def test_正文总量不超整段预算():
    text = build_context(_state(*_full(*[MAX_EVIDENCE_CHARS * 2] * 6)))

    # 预算逐条发放，正文（x）合计一定在上限内 —— 超出的只可能是元信息
    assert text.count("x") <= MAX_CONTEXT_CHARS


def test_截断只发生在渲染里_不改_evidence_本身():
    item = _evidence(1, chars=MAX_EVIDENCE_CHARS * 3)
    state = _state(item)

    text = build_context(state)

    # 渲染里砍到 2000，但 State 里保存的仍然是全文：Evidence 是事实来源
    assert text.count("x") == MAX_EVIDENCE_CHARS
    assert len(state.evidence[0].content) == MAX_EVIDENCE_CHARS * 3
    assert item.content == "x" * (MAX_EVIDENCE_CHARS * 3)


def test_空_evidence_列表行为不变():
    text = build_context(_state())

    assert "（当前还没有收集到任何 Evidence）" in text
    assert "### " not in text
