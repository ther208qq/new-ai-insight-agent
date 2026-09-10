"""State → LLM Context 的组织。

把 State 里已有的 Evidence 渲染成一段文本，交给 LLM 判断「信息够不够」。
和 graph/evidence.py 一样，这里只做搬运和排版，不做概括、不做改写：
Evidence 是事实来源，一旦经过加工，LLM 的判断依据就不再等于事实本身。

Evidence 的排布顺序沿用 state.evidence 的收集顺序（先 metadata 后 readme），
顺序稳定，模型看到的内容才是可复现的。
"""

from app.graph.state import KnowledgeProcessState

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


def build_context(state: KnowledgeProcessState) -> str:
    """把 state.evidence 渲染成给 LLM 看的 Context 文本。"""
    if not state.evidence:
        return _EMPTY

    blocks = [
        _render_evidence(index, evidence)
        for index, evidence in enumerate(state.evidence, start=1)
    ]

    context = "\n\n".join(blocks)

    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + _CONTEXT_TRUNCATION_NOTICE

    return context


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
