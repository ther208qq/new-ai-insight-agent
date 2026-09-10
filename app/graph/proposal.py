"""ProposalDraft → KnowledgeProposal 的组装。

LLM 只负责判断（概括、归纳、命名），草稿里的 evidence 只有编号；
把编号换回 State 里的原文、把 title 填上，是代码的活 —— 这两样代码都
确定知道答案，让 LLM 再写一遍只会引入它写错的可能。

和 graph/context.py 是同一层的一对：
    context.py   State        → 给 LLM 看的文本
    proposal.py  LLM 草稿 + State → 最终结构

纯函数：不调 LLM、不调 Tool、不碰 State 以外的东西，也不修改传入的 State。
"""

from app.graph.state import KnowledgeProcessState
from app.schemas.evidence import Evidence
from app.schemas.knowledge import (
    Architecture,
    Feature,
    KnowledgeProposal,
    ProposalDraft,
    Technology,
)


class EvidenceReferenceError(ValueError):
    """LLM 引用了不存在的 Evidence 编号。"""


def build_proposal(
    draft: ProposalDraft,
    state: KnowledgeProcessState,
    *,
    title: str,
) -> KnowledgeProposal:
    """把草稿与代码确定的信息拼成 KnowledgeProposal。

    title 由调用方给出（KnowledgeAgent 用 owner/repo），不取自草稿 ——
    草稿里根本没有这个字段。
    """
    return KnowledgeProposal(
        title=title,
        summary=draft.summary,
        problem=draft.problem,
        core_features=[
            Feature(
                description=feature.description,
                evidence=_resolve_evidence(
                    state, feature.evidence_refs, where="core_features"
                ),
            )
            for feature in draft.core_features
        ],
        technologies=[
            Technology(
                name=technology.name,
                category=technology.category,
                evidence=_resolve_evidence(
                    state, technology.evidence_refs, where="technologies"
                ),
            )
            for technology in draft.technologies
        ],
        architecture=Architecture(
            pattern=draft.architecture.pattern,
            components=draft.architecture.components,
            workflow=draft.architecture.workflow,
            key_design=draft.architecture.key_design,
            evidence=_resolve_evidence(
                state, draft.architecture.evidence_refs, where="architecture"
            ),
        ),
        learning_points=list(draft.learning_points),
    )


def _resolve_evidence(
    state: KnowledgeProcessState,
    refs: list[int],
    *,
    where: str,
) -> list[Evidence]:
    """编号 → State 里的 Evidence 原文。

    Context 里的编号从 1 开始（见 context.py 的 _render_evidence），这里用
    ref - 1 取下标。越界就报错而不是跳过：编号对不上说明 LLM 在编造引用，
    静默丢掉会让提案带着无法回溯的结论落库（设计文档第九节）。

    同一份 Evidence 被多个字段、甚至同一字段重复引用都正常 —— 这里不做
    「一个字段一个 Evidence」的机械限制，也不去重。
    """
    for ref in refs:
        if not 1 <= ref <= len(state.evidence):
            raise EvidenceReferenceError(
                f"{where} 引用了不存在的 Evidence 编号 [{ref}]；"
                f"当前只有 1~{len(state.evidence)}"
            )

    return [state.evidence[ref - 1] for ref in refs]
