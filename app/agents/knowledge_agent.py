"""Knowledge Agent。

给定一个 GitHub 项目的 owner / repo，分两层：

1. 采集（已有）：get_project_metadata + get_readme → Evidence → State.evidence，
   调什么、按什么顺序写死在 initialize_state() 里，全程没有 LLM 参与。
2. 决策（已有）：把 State 里已有的 Evidence 组织成 Context 交给 LLM，
   由 LLM 输出一个 AgentDecision —— 信息不够就指名下一个要调的 Tool，
   够了就 finish。
3. 执行（已有）：AgentDecision(action="tool_call") → 找到 Tool → 执行 →
   Tool Result 转成 Evidence → 追加进 State.evidence。
4. 调查循环（已有）：investigate() 把 2 和 3 串起来 —— 反复
   「决策 → 执行 → 再决策」，直到 LLM 说 finish。
5. 提案生成（本阶段新增）：generate_proposal() 拿调查完的 State 再问一次 LLM，
   把 Evidence 归纳成 KnowledgeProposal 写进 State.proposal。

分工是刻意的：decide() 只决策一次，execute() 只执行一次，generate_proposal()
只生成一次，谁都不含循环；循环只存在于 investigate() 里。run() 自身不含逻辑，
只是把「采集 → 调查 → 生成提案」三步串起来。Harness、Reflection 仍未实现。
"""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.agents.prompts import DECISION_SYSTEM_PROMPT, PROPOSAL_SYSTEM_PROMPT
from app.graph.context import build_context
from app.graph.evidence import (
    document_to_evidence,
    metadata_to_evidence,
    record_evidence,
    search_to_evidence,
    structure_to_evidence,
)
from app.graph.proposal import EvidenceReferenceError, build_proposal
from app.graph.state import KnowledgeProcessState, Source
from app.llm.client import LLMClient, LLMNotConfiguredError
from app.schemas.decision import AgentDecision
from app.schemas.evidence import Evidence
from app.schemas.knowledge import ProposalDraft
from app.tools.get_project_metadata import get_project_metadata
from app.tools.get_readme import get_readme
from app.tools.registry import call_tool


MAX_TOOL_CALLS = 5

EVIDENCE_CONVERTERS: dict[str, Callable[[Any], Evidence]] = {
    "get_project_structure": structure_to_evidence,
    "get_file": document_to_evidence,
    "search_code": search_to_evidence,
}


class NotAToolCallError(RuntimeError):
    """execute() 收到了一个不是 tool_call 的决策，或者它缺少 tool_name。"""


class KnowledgeAgent:
    """一次运行 = 一个实例。

    llm 不传时 Agent 仍可采集证据，只是不能做决策、也不能生成提案 ——
    用到 LLM 的那一刻才报错，这样「暂时没接 LLM」不会连采集都用不了。
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        llm: LLMClient | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.llm = llm
        self.source = Source(
            url=f"https://github.com/{owner}/{repo}",
            type="github",
        )

    def initialize_state(self) -> KnowledgeProcessState:
        """新建 State，并固定采集基础信息（metadata + README）。

        每调用一次都会新建一个 State（process_id 是新的），
        所以两次调用之间不会互相污染。

        调什么 Tool、按什么顺序，全写死在这里 —— 全程没有 LLM 参与。
        只想要采集结果、还不想接 LLM 时，调这个方法（run() 后两步都要 LLM）。
        """
        state = KnowledgeProcessState(
            process_id=uuid4().hex,
            source=self.source,
            status="collecting",
        )

        # 两个 Tool 的返回值由代码转成 Evidence
        return record_evidence(
            state,
            metadata_to_evidence(get_project_metadata(self.owner, self.repo)),
            document_to_evidence(get_readme(self.owner, self.repo)),
        )

    def run(self) -> KnowledgeProcessState:
        """完整流程：采集 → 调查 → 生成提案。

            initialize_state → investigate → generate_proposal

        自身不含任何逻辑，只是把三步串起来。后两步都要 LLM，所以没配 LLM 时
        会在那一步报错；只想要采集结果就调 initialize_state()。
        """
        state = self.initialize_state()
        state = self.investigate(state)
        return self.generate_proposal(state)

    def build_context(self, state: KnowledgeProcessState) -> str:
        """把 State 中已有的 Evidence 组织成交给 LLM 的 Context。"""
        return build_context(state)

    def decide(self, state: KnowledgeProcessState) -> AgentDecision:
        """让 LLM 基于当前 State 决定下一步，返回 AgentDecision。

        范围是：State → Context → LLM → AgentDecision。
        返回的决策**不会**在这里执行 —— 执行是 execute() 的事。
        """
        if self.llm is None:
            raise LLMNotConfiguredError(
                "KnowledgeAgent 没有配置 LLM，无法做决策（构造时传入 llm=...）"
            )

        return self.llm.complete(
            system=DECISION_SYSTEM_PROMPT,
            user=self.build_context(state),
            response_model=AgentDecision,
        )

    def execute(
        self,
        state: KnowledgeProcessState,
        decision: AgentDecision,
    ) -> KnowledgeProcessState:
        """执行一个 tool_call 决策，返回追加了 Evidence 的新 State。

            AgentDecision(tool_call) → Tool → Tool Result → Evidence → State

        和 run() / record_evidence 一样不修改传入的 state，返回的是新对象。

        **只做一步**：执行完就结束，不会回头再问 LLM「下一步干嘛」，
        也不动 tool_call_count。「决策 → 执行 → 再决策」的往复在
        investigate() 里。

        当前可执行的 Tool 只有 registry.ALLOWED_TOOLS 里登记的那几个，
        指名其他 Tool 会抛 UnsupportedToolError。
        """
        if decision.action != "tool_call":
            raise NotAToolCallError(
                f"execute() 只处理 action='tool_call' 的决策，收到 {decision.action!r}"
            )

        # tool_call 时 tool_name 理应有值，但 schema 没强制（它是 str | None），
        # 所以这个洞必须在这里兜住，否则会漏到 call_tool 变成难懂的报错。
        if decision.tool_name is None:
            raise NotAToolCallError("action='tool_call' 但 tool_name 为 None")

        tool_result = call_tool(
            decision.tool_name,
            decision.tool_arguments,
            owner=self.owner,
            repo=self.repo,
        )

        converter = EVIDENCE_CONVERTERS[decision.tool_name]
        return record_evidence(state, converter(tool_result))

    def investigate(self, state: KnowledgeProcessState) -> KnowledgeProcessState:
        """Tool Calling Loop：反复「决策 → 执行」直到 LLM 说够了。

            decide ─ finish ──────────────────────────→ 返回 state
              │
              └─ tool_call → execute → 新 Evidence 进 state → 回到 decide

        传入的是已有 State，investigate() 不会新建 State（那是 run() 的事），
        也不修改传入对象 —— 每轮 execute() 返回的新 State 就是下一轮 decide()
        的输入，LLM 因此能看到刚补进来的 Evidence。

        退出只有两条路：

        1. decide() 返回 finish —— 正常结束，此时不再执行任何 Tool。
        2. state.tool_call_count 达到 MAX_TOOL_CALLS —— 安全上限。

        上限是兜底，不是正常完成条件：LLM 若是反复要同一个 Tool（或换着花样
        要），循环仍然会停，不会无限转下去。但它**不是**「调查完成」的意思，
        所以返回的 State 依然是 status="collecting"。

        注意：因为要在一轮开始时就知道还剩多少额度，上限是在 decide() 之前
        检查的。所以达到上限时不会再多问 LLM 一次，也就不存在「最后一次决策
        被丢弃」的浪费。
        """
        while state.tool_call_count < MAX_TOOL_CALLS:
            decision = self.decide(state)


            if decision.action == "finish":
                return state

            # execute() 只负责执行并追加 Evidence，计数由循环自己记 ——
            # 「还能调用几次」是循环的事，不该塞进单步职责里。
            state = self.execute(state, decision)
            state = state.model_copy(
                update={"tool_call_count": state.tool_call_count + 1}
            )

        return state

    def generate_proposal(
        self, state: KnowledgeProcessState
    ) -> KnowledgeProcessState:
        """把调查完的 Evidence 归纳成 KnowledgeProposal，写进 State。

            Evidence → Context → LLM(ProposalDraft) → 代码回填 → KnowledgeProposal

        只做这一件事：不调 Tool、不改 Evidence、不反思、不落库、不建关系。
        investigate() 返回 finish 只意味着「Evidence 够了」，提案在这里才生成，
        所以这一步不会让 tool_call_count 变化。

        字段分工：title 与每条 evidence 的正文由代码填（owner/repo 与
        state.evidence 里的原文），其余字段由 LLM 归纳 —— 见 build_proposal()。

        和 run() / investigate() 一样不修改传入的 state。失败时返回的是
        status="failed" 的新 State，而不是抛错（见 _failed）。
        """
        if self.llm is None:
            raise LLMNotConfiguredError(
                "KnowledgeAgent 没有配置 LLM，无法生成提案（构造时传入 llm=...）"
            )

        # 没有 Evidence 就没有可归纳的对象。这里不抛错而是落成失败状态 ——
        # 凭空写一份提案就是设计文档里说的「静默返回一个假 Proposal」。
        if not state.evidence:
            return _failed(state, "没有 Evidence，无法生成 KnowledgeProposal")

        try:
            draft = self.llm.complete(
                system=PROPOSAL_SYSTEM_PROMPT,
                user=self.build_context(state),
                response_model=ProposalDraft,
            )
        except ValidationError as error:
            # ValidationError 只可能来自 LLM 的输出 —— 校验在 LLM 边界发生，
            # 拼装成品时再炸的话是代码的 bug，不该被这里吞掉。
            return _failed(state, f"LLM 输出不符合 ProposalDraft：{error}")

        try:
            proposal = build_proposal(
                draft, state, title=f"{self.owner}/{self.repo}"
            )
        except EvidenceReferenceError as error:
            return _failed(state, str(error))

        return state.model_copy(
            update={"proposal": proposal, "status": "analyzing"}
        )


def _failed(
    state: KnowledgeProcessState, message: str
) -> KnowledgeProcessState:
    """把 State 落成失败态，返回新对象（不修改传入的 state）。

    提案一并置回 None：失败态不该留着一份（可能来自上一次调用的）旧提案。
    """
    return state.model_copy(
        update={"proposal": None, "status": "failed", "error": message}
    )
