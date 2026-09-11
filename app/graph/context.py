"""State → LLM Context 的组织。

把 State 里已有的 Evidence 渲染成一段文本，交给 LLM 判断「信息够不够」。
和 graph/evidence.py 一样，这里只做搬运和排版，不做概括、不做改写：
Evidence 是事实来源，一旦经过加工，LLM 的判断依据就不再等于事实本身。

Evidence 的排布顺序沿用 state.evidence 的收集顺序（先 metadata 后 readme），
顺序稳定，模型看到的内容才是可复现的。

这里有两个入口，取决于 LLM 那一轮要看什么：

    build_context            State                调查阶段：Evidence 够不够
    build_reflection_context Proposal + Evidence  反思阶段：提案站不站得住

build_context 会按顺序渲染三段：Evidence、上一轮 Proposal、Reflection Result。
后两段只在对应字段非空时出现 —— 第一次跑时 State 里两者都是 None，渲染出来的
就只有 Evidence，与从前一致。它们是为「重跑」准备的：Agent 因此能看见自己上一版
写了什么、Reviewer 又指出了哪些问题，进而针对 Issue 去补证据，而不是把上一版
原样再生成一遍。
"""

import json

from app.graph.state import KnowledgeProcessState
from app.schemas.evidence import Evidence
from app.schemas.knowledge import KnowledgeProposal
from app.schemas.reflection import ReflectionResult

# 单条 Evidence 放进 Context 的长度上限。真实仓库的 README / 源码动辄几万字符，
# 直接塞进 Prompt 会撑爆上下文；截断只影响「给 LLM 看多少」，不影响 state 里
# 保存的内容本身。
MAX_EVIDENCE_CHARS = 2000

# 整段 Context 的长度上限。多条 Evidence 各自没超，加起来仍可能超。
MAX_CONTEXT_CHARS = 8000

_EMPTY = "（当前还没有收集到任何 Evidence）"

_TRUNCATION_NOTICE = "（内容过长，已截断）"

# Context 被截断时会丢掉后面的 Evidence，必须显式告诉模型，
# 否则它会把「没看到」当成「不存在」，进而少调工具或误判信息已经足够。
_CONTEXT_TRUNCATION_NOTICE = "\n\n（以上 Evidence 仅展示了前面一部分，后面还有内容未展示）"

_EVIDENCE_TEMPLATE = """### [{index}] {evidence_type}
- source: {source}
- location: {location}
- content:
{content}"""

# 反思 Context 的两个小标题。调查 Context 不需要 —— 那段里只有 Evidence，
# 加标题反而多一层噪音。
_PROPOSAL_HEADER = "## 待审查的 KnowledgeProposal"

_EVIDENCE_HEADER = "## 可用的 Evidence"


def build_context(state: KnowledgeProcessState) -> str:
    """把 State 渲染成给 Knowledge Agent 决策 / 提案用的 Context。

        固定顺序：Evidence → Previous Proposal → Reflection Result

    后两段只在字段非空时追加。第一次跑时 State 里 proposal 与 reflection_result
    都是 None，Context 里就只有 Evidence —— 和接入 Reflection 之前完全一样，所以
    「首轮行为不变」不需要额外的开关来保证。

    顺序是刻意的：证据在前，Agent 读到的第一件事仍然是事实；提案与反思在后，
    以「上一轮的结论，待修正」的姿态出现。

    长度上限只作用在 Evidence 上（见 _render_evidence_list）。Proposal 与
    Reflection Result 不截断 —— 前者是待修正的对象，后者是必须被逐条处理的
    行动清单，任何一段被截掉都会让 Agent 把「没看到」当成「不存在」，从而漏掉
    该补的证据。两者内嵌的 Evidence 正文都已被压成 location（见 _render_proposal
    与 _render_reflection_result），所以不截断也不会撑爆额度。
    """
    sections = ["## Evidence\n" + _render_evidence_list(state.evidence)]

    if state.proposal is not None:
        sections.append("## Previous Proposal\n" + _render_proposal(state.proposal))

    if state.reflection_result is not None:
        sections.append(
            "## Reflection Result\n"
            + _render_reflection_result(state.reflection_result)
        )

    return "\n\n".join(sections)


def build_reflection_context(
    proposal: KnowledgeProposal,
    evidence: list[Evidence],
) -> str:
    """Proposal + Evidence → 交给 Reflection 的文本。

    和 build_context 一样只做搬运和排版，不做概括、不做改写。两处刻意的不同：

    1. Proposal 在前、Evidence 在后。Reflection 要审查的是 Proposal，证据是
       判断依据，顺序反过来读起来才是「先看结论、再核依据」。
    2. 长度上限只作用在 Evidence 上，Proposal 不截断 —— 它正是被审查的对象，
       看一半会让 LLM 把「没看到」当成「不存在」，报出一堆其实存在、只是被截掉
       的字段（和 _CONTEXT_TRUNCATION_NOTICE 要解决的是同一类误判）。
    """
    return (
        f"{_PROPOSAL_HEADER}\n\n{_render_proposal(proposal)}\n\n"
        f"{_EVIDENCE_HEADER}\n\n{_render_evidence_list(evidence)}"
    )


def _render_evidence_list(evidence: list[Evidence]) -> str:
    """把一串 Evidence 渲染成文本，并套上两层长度上限。

    build_context 与 build_reflection_context 共用 —— 截断规则只该有一处，
    否则「给 LLM 看多少」会随调用点不同而不同。编号（[n]）也由这里统一给出，
    两个入口看到的编号规则因此必然一致。
    """
    if not evidence:
        return _EMPTY

    blocks = [
        _render_evidence(index, item)
        for index, item in enumerate(evidence, start=1)
    ]

    text = "\n\n".join(blocks)

    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS] + _CONTEXT_TRUNCATION_NOTICE

    return text


def _render_proposal(proposal: KnowledgeProposal) -> str:
    """Proposal → 文本，内嵌的 evidence 只留出处。

    提案里每个字段自己带 evidence（Feature / Technology / Architecture 都有），
    正文在 Evidence 段里已经逐条列过，再嵌一遍是重复占额度。留 location 是为了
    让 LLM 看得出提案声称引用了哪些证据 —— 声称引用了、实际支撑不住，正是
    Reflection 要抓的东西，而重跑时 Agent 也得看见自己上一版引的是哪几条。

    ensure_ascii=False：这些内容大多是中文，转义成 \\uXXXX 只是白烧 token。
    """
    data = proposal.model_dump()

    for feature in data["core_features"]:
        feature["evidence"] = _citations(feature["evidence"])
    for technology in data["technologies"]:
        technology["evidence"] = _citations(technology["evidence"])
    data["architecture"]["evidence"] = _citations(data["architecture"]["evidence"])

    return json.dumps(data, ensure_ascii=False, indent=2)


def _render_reflection_result(result: ReflectionResult) -> str:
    """ReflectionResult → 文本，每条 Issue 的证据只留出处。

    和 _render_proposal 同一个理由：证据正文在 Evidence 段里已经列过，再嵌一遍
    是重复占额度。Reflection 的价值在于「结论可回溯到证据」，留 location 就够
    Agent 看出 Reviewer 指的是哪一条 —— 它要据此决定去补什么证据。

    description 与 summary 原样保留：那是 Reviewer 要说的话，是这份反馈的主体，
    压缩它就等于把反馈本身弄丢。只有 evidence 字段被压成 location。
    """
    data = result.model_dump()

    for issue in data["issues"]:
        issue["evidence"] = _citations(issue["evidence"])

    return json.dumps(data, ensure_ascii=False, indent=2)


def _citations(evidence: list[dict]) -> list[str]:
    """把一份份 Evidence 压成它们的出处。"""
    return [item["location"] for item in evidence]


def _render_evidence(index: int, evidence) -> str:
    content = evidence.content.strip()
    if len(content) > MAX_EVIDENCE_CHARS:
        content = content[:MAX_EVIDENCE_CHARS].rstrip() + _TRUNCATION_NOTICE

    return _EVIDENCE_TEMPLATE.format(
        index=index,
        evidence_type=evidence.evidence_type,
        source=evidence.source,
        location=evidence.location,
        content=content,
    )
