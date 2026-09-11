"""ReflectionDraft → ReflectionResult 的组装。

LLM 只负责判断（哪里不对、属于哪一类、为什么），草稿里的 evidence 只有编号；
把编号换回传入 Evidence 的原文是代码的活。这和 graph/proposal.py 是同一条
规则的两处应用：

    proposal.py    ProposalDraft   + State.evidence → KnowledgeProposal
    reflection.py  ReflectionDraft + Evidence[]     → ReflectionResult

不这么做的后果很具体：ReflectionIssue.evidence 是完整的 Evidence 对象，让
LLM 直接填，它就能写出一份输入里根本不存在的证据 —— 四个字段全是自由文本，
schema 一个都校验不出来。Reflection 的价值就在于「结论可回溯到证据」，
那样就没了。

纯函数：不调 LLM、不调 Tool、不碰数据库，也不修改传入的 evidence。
"""

from app.graph.proposal import EvidenceReferenceError
from app.schemas.evidence import Evidence
from app.schemas.reflection import (
    ReflectionDraft,
    ReflectionIssue,
    ReflectionResult,
)


def build_reflection_result(
    draft: ReflectionDraft,
    evidence: list[Evidence],
) -> ReflectionResult:
    """把反思草稿与编号对应的 Evidence 原文拼成 ReflectionResult。

    passed / summary 原样取草稿（那是 LLM 的判断）；issues 里每条的证据由
    代码按编号回填 —— 只有编号是 LLM 写的，正文出自输入的 evidence。
    """
    return ReflectionResult(
        passed=draft.passed,
        issues=[
            ReflectionIssue(
                field=issue.field,
                type=issue.type,
                description=issue.description,
                evidence=_resolve_evidence(
                    evidence, issue.evidence_refs, where=issue.field
                ),
            )
            for issue in draft.issues
        ],
        summary=draft.summary,
    )


def _resolve_evidence(
    evidence: list[Evidence],
    refs: list[int],
    *,
    where: str,
) -> list[Evidence]:
    """编号 → 输入 evidence 里的原文。

    编号从 1 开始（见 context.py 的 _render_evidence），这里用 ref - 1 取下标。
    越界就报错而不是跳过：编号对不上说明 LLM 在编造引用，静默丢掉会让 issue
    带着一个指向不存在证据的结论留下来 —— 而「只能引用输入的 Evidence」
    正是 Reflection 存在的理由。

    异常沿用 proposal.py 的 EvidenceReferenceError：两个模块执行的是同一条
    规则，没必要各定义一份同义的异常。
    """
    for ref in refs:
        if not 1 <= ref <= len(evidence):
            raise EvidenceReferenceError(
                f"{where} 引用了不存在的 Evidence 编号 [{ref}]；"
                f"当前只有 1~{len(evidence)}"
            )

    return [evidence[ref - 1] for ref in refs]
