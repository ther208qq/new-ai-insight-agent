"""Reflection 相关的测试。

FakeLLM 的草稿是脚本里写死的，所以这里测不出「LLM 审得好不好」——「某个 claim
到底该判 factual_error 还是 unsupported_claim」是 LLM 的判断，脚本写什么就出
什么（见 test_issue_类型原样来自_llm）。这里测的是装配关系：

- 编号有没有真的换回输入的 Evidence 原文
- passed / issues / summary 有没有真的进到 ReflectionResult 里
- Reflection 有没有越界去调 Tool

编号规则沿用 context.py：输入的 evidence 从 1 开始编号。
"""

import pytest
from pydantic import ValidationError

from app.agents.reflection import ReflectionReviewer
from app.graph.proposal import EvidenceReferenceError
from app.llm import FakeLLM
from app.schemas.evidence import Evidence
from app.schemas.knowledge import (
    Architecture,
    Feature,
    KnowledgeProposal,
    Technology,
)

_PASS = {
    "passed": True,
    "issues": [],
    "summary": "提案的事实性内容都能从 Evidence 得到支持。",
}


def _evidence() -> list[Evidence]:
    """输入给 Reflection 的两条证据：编号 [1] metadata、[2] readme。

    每次新建，避免测试之间共享同一批对象。
    """
    return [
        Evidence(
            source="github",
            location="https://github.com/example/demo-project",
            content='{"name": "demo-project", "language": "Python"}',
            evidence_type="metadata",
        ),
        Evidence(
            source="github",
            location="README.md",
            content="# Demo Project\n\n一个用于演示 Knowledge Agent 的示例仓库。",
            evidence_type="readme",
        ),
    ]


def _proposal() -> KnowledgeProposal:
    return KnowledgeProposal(
        title="example/demo-project",
        summary="一个用来演示 Knowledge Agent 的示例仓库。",
        problem="验证 Evidence 能否被归纳成可落库的知识。",
        core_features=[
            Feature(description="固定采集 metadata 与 README"),
        ],
        technologies=[
            Technology(name="Python", category="language"),
        ],
        architecture=Architecture(
            pattern="",
            components=["KnowledgeAgent"],
            workflow="采集 → 调查 → 生成提案",
        ),
        learning_points=["Evidence 由代码生成，不交给 LLM"],
    )


def _issue(**overrides) -> dict:
    issue = {
        "field": "technologies",
        "type": "factual_error",
        "description": "提案称使用 PostgreSQL，但 Evidence 显示实际使用的是 SQLite。",
        "evidence_refs": [2],
    }
    return {**issue, **overrides}


def _draft(**overrides) -> dict:
    draft = {**_PASS, "passed": False, "issues": [_issue()]}
    return {**draft, **overrides}


# --- 设计第十一节的五个 Test -----------------------------------------------


def test_1_全部通过():
    reviewer = ReflectionReviewer(FakeLLM(_PASS))

    result = reviewer.run(_proposal(), _evidence())

    assert result.passed is True
    assert result.issues == []
    assert result.summary == _PASS["summary"]


def test_2_事实错误():
    reviewer = ReflectionReviewer(FakeLLM(_draft()))

    result = reviewer.run(_proposal(), _evidence())

    assert result.passed is False
    assert [issue.type for issue in result.issues] == ["factual_error"]
    assert result.issues[0].field == "technologies"


def test_3_无证据支撑():
    draft = _draft(
        issues=[
            _issue(
                type="unsupported_claim",
                description="提案称使用 Redis，但 Evidence 里没有任何 Redis 相关内容。",
                evidence_refs=[],
            )
        ]
    )
    reviewer = ReflectionReviewer(FakeLLM(draft))

    result = reviewer.run(_proposal(), _evidence())

    assert result.passed is False
    assert result.issues[0].type == "unsupported_claim"
    # 找不到依据时本来就没有证据可引用，空列表是正常结果
    assert result.issues[0].evidence == []


def test_4_evidence_之间冲突():
    draft = _draft(
        issues=[
            _issue(
                type="contradiction",
                description="两条 Evidence 对使用的数据库给出不同信息，无法可靠判断。",
                evidence_refs=[1, 2],
            )
        ]
    )
    reviewer = ReflectionReviewer(FakeLLM(draft))

    result = reviewer.run(_proposal(), _evidence())

    assert result.passed is False
    assert result.issues[0].type == "contradiction"
    assert len(result.issues[0].evidence) == 2


def test_5_reflection_不调用_Tool(monkeypatch):
    from app.agents import reflection as module
    from app.tools import registry

    def _boom(*args, **kwargs):
        raise AssertionError("Reflection 不应该调用 Tool")

    monkeypatch.setattr(registry, "call_tool", _boom)

    result = ReflectionReviewer(FakeLLM(_PASS)).run(_proposal(), _evidence())

    assert result.passed is True
    # 模块根本没把 Tool 引进来 —— 不是「碰巧这条路径没调到」
    assert not hasattr(module, "call_tool")


# --- 装配关系 ---------------------------------------------------------------


def test_issue_的_evidence_正文来自输入而不是_llm():
    evidence = _evidence()
    reviewer = ReflectionReviewer(FakeLLM(_draft()))

    result = reviewer.run(_proposal(), evidence)

    # 草稿里只写了编号 [2]，结果里必须是输入的那条原文本身
    cited = result.issues[0].evidence
    assert cited[0] is evidence[1]
    assert cited[0].location == "README.md"


def test_编号从一开始对应输入列表():
    draft = _draft(issues=[_issue(evidence_refs=[1])])
    evidence = _evidence()

    result = ReflectionReviewer(FakeLLM(draft)).run(_proposal(), evidence)

    assert result.issues[0].evidence[0] is evidence[0]
    assert result.issues[0].evidence[0].evidence_type == "metadata"


def test_引用不存在的编号会报错():
    draft = _draft(issues=[_issue(evidence_refs=[99])])
    reviewer = ReflectionReviewer(FakeLLM(draft))

    with pytest.raises(EvidenceReferenceError) as error:
        reviewer.run(_proposal(), _evidence())

    assert "[99]" in str(error.value)


def test_issue_类型原样来自_llm():
    # 判断哪一类 issue 是 LLM 的活，代码不做二次推断 —— 这里脚本给什么就出什么
    draft = _draft(issues=[_issue(type="missing_evidence")])

    result = ReflectionReviewer(FakeLLM(draft)).run(_proposal(), _evidence())

    assert result.issues[0].type == "missing_evidence"


def test_多条_issue_各自回填自己的证据():
    draft = _draft(
        issues=[
            _issue(field="technologies", evidence_refs=[2]),
            _issue(field="core_features", type="unsupported_claim", evidence_refs=[1]),
        ]
    )
    evidence = _evidence()

    result = ReflectionReviewer(FakeLLM(draft)).run(_proposal(), evidence)

    assert [issue.field for issue in result.issues] == ["technologies", "core_features"]
    assert result.issues[0].evidence[0] is evidence[1]
    assert result.issues[1].evidence[0] is evidence[0]


def test_用的是_reflection_自己的_prompt():
    llm = FakeLLM(_PASS)
    ReflectionReviewer(llm).run(_proposal(), _evidence())

    assert len(llm.calls) == 1
    assert "Evidence-grounded Reviewer" in llm.calls[0]["system"]
    # 结果要符合 ReflectionResult（能被 schema 重新校验一遍）
    assert "evidence_refs" in llm.calls[0]["system"]


def test_context_里_proposal_和_evidence_都有():
    llm = FakeLLM(_PASS)
    ReflectionReviewer(llm).run(_proposal(), _evidence())

    user = llm.calls[0]["user"]
    assert "待审查的 KnowledgeProposal" in user
    assert "可用的 Evidence" in user
    # proposal 的字段与 evidence 的出处都真的进去了
    assert "example/demo-project" in user
    assert "README.md" in user
    assert "[1] metadata" in user


def test_proposal_内嵌的_evidence_只留出处():
    # Proposal 里每个字段自己也带 evidence（真实链路里由 build_proposal 回填）。
    # 正文在「可用的 Evidence」段列一次就够了，提案段里只留 location。
    evidence = _evidence()
    proposal = _proposal()
    proposal.technologies[0].evidence = [evidence[1]]

    llm = FakeLLM(_PASS)
    ReflectionReviewer(llm).run(proposal, evidence)

    proposal_part, evidence_part = llm.calls[0]["user"].split("## 可用的 Evidence")
    assert "README.md" in proposal_part
    assert "# Demo Project" not in proposal_part
    assert "# Demo Project" in evidence_part


def test_proposal_不参与截断():
    # 提案是被审查的对象，看一半会让 LLM 把「没截到」当成「不存在」
    long_summary = "很长" * 5000
    proposal = _proposal().model_copy(update={"summary": long_summary})
    huge = [
        Evidence(
            source="github",
            location="big.py",
            content="x" * 20000,
            evidence_type="code",
        )
    ]

    llm = FakeLLM(_PASS)
    ReflectionReviewer(llm).run(proposal, huge)

    proposal_part, evidence_part = llm.calls[0]["user"].split("## 可用的 Evidence")
    assert long_summary in proposal_part
    # 长度上限只作用在 Evidence 上
    assert "内容过长，已截断" in evidence_part


def test_llm_输出不合法会抛出():
    draft = {**_PASS, "extra_field": "schema 里没有这个字段"}

    with pytest.raises(ValidationError):
        ReflectionReviewer(FakeLLM(draft)).run(_proposal(), _evidence())


def test_不修改传入的_proposal_和_evidence():
    proposal = _proposal()
    evidence = _evidence()
    proposal_before = proposal.model_dump()
    evidence_before = [item.model_dump() for item in evidence]

    ReflectionReviewer(FakeLLM(_draft())).run(proposal, evidence)

    assert proposal.model_dump() == proposal_before
    assert [item.model_dump() for item in evidence] == evidence_before
