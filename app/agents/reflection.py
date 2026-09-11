"""Reflection：Evidence-grounded Reviewer。

职责只有一件：检查 KnowledgeProposal 里的事实性内容能否被已有 Evidence 支持。

    Proposal + Evidence → Review → ReflectionResult

它**不是** Agent，也不该长成 Agent：

- 不持有 Tool，不调 Tool，更不做 Tool Calling Loop
- 不获取新 Evidence —— 只审查传进来的这些，不去外面找
- 不修改 Proposal，也不重新生成 Proposal
- 不决定下一步 Workflow

证据不足时它只记录 Issue，不自己补事实、也不替 Proposal 改错。把 Issue 反馈给
Knowledge Agent 是外层 Workflow 的事 —— 那一步不在本模块（本阶段只做 Reflection，
不实现重试与外层循环）。

范围上它是 generate_proposal() 的镜像：那个是「Evidence → 提案」，这个是
「提案 + Evidence → 审查」。两者的输入都只有数据、输出都只有结构，都不碰 Tool。
"""

from app.agents.prompts import REFLECTION_SYSTEM_PROMPT
from app.graph.context import build_reflection_context
from app.graph.reflection import build_reflection_result
from app.llm.client import LLMClient
from app.schemas.evidence import Evidence
from app.schemas.knowledge import KnowledgeProposal
from app.schemas.reflection import ReflectionDraft, ReflectionResult


class ReflectionReviewer:
    """一次审查 = 一个实例。

    llm 是必填的：Reflection 从头到尾只有「问 LLM」这一件事，没有不接 LLM
    也能跑的部分。KnowledgeAgent 的 llm 之所以可选，是因为它的采集阶段不需要
    LLM —— 那个理由在这里不成立，所以不照抄。
    """

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        proposal: KnowledgeProposal,
        evidence: list[Evidence],
    ) -> ReflectionResult:
        """审查 proposal 能否被 evidence 支持，返回 ReflectionResult。

            Proposal + Evidence → Context → LLM(ReflectionDraft) → 代码回填
                                → ReflectionResult

        只做这一件事：不调 Tool、不清空或追加 Evidence、不碰 State、不改
        Proposal。传入的 proposal 与 evidence 都不会被修改。

        LLM 输出不合法（ValidationError）或引用了不存在的 Evidence 编号
        （EvidenceReferenceError）时**直接抛出**，不在这里兜成「审查失败」——
        ReflectionResult 里没有 error 字段，没有地方安放一个失败态，而这两种
        异常都说明 LLM 的输出该被看见。外层 Workflow 怎么处理（重试 / 落成
        failed State），等实现它时再定。
        """
        draft = self.llm.complete(
            system=REFLECTION_SYSTEM_PROMPT,
            user=build_reflection_context(proposal, evidence),
            response_model=ReflectionDraft,
        )

        return build_reflection_result(draft, evidence)
