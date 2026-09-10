"""Knowledge Agent。

给定一个 GitHub 项目的 owner / repo，分两层：

1. 采集（已有）：get_project_metadata + get_readme → Evidence → State.evidence，
   调什么、按什么顺序写死在 run() 里，全程没有 LLM 参与。
2. 决策（已有）：把 State 里已有的 Evidence 组织成 Context 交给 LLM，
   由 LLM 输出一个 AgentDecision —— 信息不够就指名下一个要调的 Tool，
   够了就 finish。
3. 执行（已有）：AgentDecision(action="tool_call") → 找到 Tool → 执行 →
   Tool Result 转成 Evidence → 追加进 State.evidence。
4. 调查循环（本阶段新增）：investigate() 把 2 和 3 串起来 —— 反复
   「决策 → 执行 → 再决策」，直到 LLM 说 finish。

分工是刻意的：decide() 只决策一次，execute() 只执行一次，谁都不含循环；
循环只存在于 investigate() 里。Harness、Reflection、KnowledgeProposal
生成仍未实现。
"""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.agents.prompts import DECISION_SYSTEM_PROMPT
from app.graph.context import build_context
from app.graph.evidence import (
    document_to_evidence,
    metadata_to_evidence,
    record_evidence,
    search_to_evidence,
    structure_to_evidence,
)
from app.graph.state import KnowledgeProcessState, Source
from app.llm.client import LLMClient, LLMNotConfiguredError
from app.schemas.decision import AgentDecision
from app.schemas.evidence import Evidence
from app.tools.get_project_metadata import get_project_metadata
from app.tools.get_readme import get_readme
from app.tools.registry import call_tool


# investigate() 的安全上限：一轮调查最多执行多少次 Tool。
# 这是兜底，不是正常完成条件 —— 正常情况下应该由 LLM 返回 finish 来结束
# （见 investigate 的说明）。取值只需盖住「合理调查一个仓库」的量级。
MAX_TOOL_CALLS = 5

# tool_name → Tool Result 的 Evidence 转换器。
# execute() 用它把任意 Tool 的产出接进 State.evidence；也就是说，一个 Tool
# 要在执行层可用，必须在 ALLOWED_TOOLS 和这里**同时**登记 —— 只登记前者
# 会在转换时 KeyError，只登记后者不会被调用到。
EVIDENCE_CONVERTERS: dict[str, Callable[[Any], Evidence]] = {
    "get_project_structure": structure_to_evidence,
    "get_file": document_to_evidence,
    "search_code": search_to_evidence,
}


class NotAToolCallError(RuntimeError):
    """execute() 收到了一个不是 tool_call 的决策，或者它缺少 tool_name。"""


class KnowledgeAgent:
    """一次运行 = 一个实例。

    llm 不传时 Agent 仍可采集证据，只是不能做决策 —— 决策那一刻才报错，
    这样「暂时没接 LLM」不会连采集都用不了。
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

    def run(self) -> KnowledgeProcessState:
        """收集证据，返回更新后的 State。

        每调用一次都会新建一个 State（process_id 是新的），
        所以两次 run() 之间不会互相污染。
        """
        state = KnowledgeProcessState(
            process_id=uuid4().hex,
            source=self.source,
            status="collecting",
        )

        # 两个 Tool 的返回值由代码转成 Evidence —— 全程没有 LLM 参与
        state = record_evidence(
            state,
            metadata_to_evidence(get_project_metadata(self.owner, self.repo)),
            document_to_evidence(get_readme(self.owner, self.repo)),
        )

        return state

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
