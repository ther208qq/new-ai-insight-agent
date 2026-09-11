"""LangGraph 外层流程：initialize → knowledge → reflection → retry / pass。

    START
      ↓
    initialize        新建 State（采集元信息 + README）
      ↓
    knowledge         调查 + 生成提案        ←──────┐
      ↓                                            │
    reflection        审查提案站不站得住            │
      ↓                                            │
    route_after_reflection                         │
      ├─ pass  → END                               │
      ├─ failed→ END                               │
      └─ retry → prepare_retry ────────────────────┘

这一层只做「串起来」：每个节点都是现成的，workflow 自己不实现采集、不实现 Tool
Calling Loop、不实现反思、不调用 LLM、也判断不了提案好不好。它唯一新增的语义是
**循环**：审查不过就带着原 State 再走一遍 Knowledge。

循环靠 LangGraph 的 conditional edge 构成，代码里没有 while。

关于重试为什么必须复用原 State
------------------------------
重试走的是 prepare_retry → knowledge 这条边，返回的是**同一个 State**（reflection
没改过它，prepare_retry 只动 iteration_count）。绝不回头去调 initialize_state()：
那会新建一个 process_id 和空 evidence，上一轮辛苦调查出来的证据全丢，等于每轮都从
零开始 —— 而 Reflection 说的问题恰恰要靠这些证据来解决。

关于边界（本模块刻意不做的事）
------------------------------
不落库、不建关系、不做 embedding、不实现 Relation Agent、不改 proposal / evidence。
Reflection 判 pass 只是「提案站得住」，不代表已经持久化 —— 下一步该接谁，是以后的事。

入口
----
    from app.graph.workflow import build_workflow

    wf = build_workflow("example", "demo-project", llm=create_llm_client())
    final = wf.invoke(seed)          # seed 见 build_workflow 的说明

    from app.graph.workflow import build_workflow

    wf = build_workflow("example", "demo-project")
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.knowledge_agent import KnowledgeAgent
from app.graph.nodes import knowledge_node, reflection_node
from app.graph.state import KnowledgeProcessState
from app.llm import create_llm_client
from app.llm.client import LLMClient


class MissingReflectionResultError(RuntimeError):
    """走到路由时 reflection_result 仍是 None。

    这不是「反思没通过」，而是「反思压根没跑」。反思节点只要跑到就会写回
    reflection_result（除非它在更早的地方就落成了别的状态，那种情况由 status 兜住），
    所以这里为 None 只能是图接错了 —— 属于代码 bug，不该被当成一次正常的失败吞掉。
    """


def route_after_reflection(state: KnowledgeProcessState) -> str:
    """决定 reflection 之后走哪条边：\"pass\" / \"retry\" / \"failed\"。

    纯函数：不改 State、不调 Agent、不调 LLM、不执行循环。它只回答一个问题。

    1. status == "failed" → "failed"
       上一轮 Knowledge 已经落成失败态（没有 Evidence、LLM 输出不合法、引用了不存在
       的证据编号……见 knowledge_node 的说明）。失败态是**数据**不是异常 —— 仓库既有
       约定就是这样：generate_proposal() 失败时返回 failed State 而不抛错，main.py
       也是先看 status/error 再决定怎么打印。所以这里让它去 END，把失败原样交给调用方。

       这一步不能省：失败时 proposal 为 None，而 **reflection_result 可能还留着上一轮
       的值**（knowledge_agent._failed 只把 proposal 置回 None）。若先看 reflection_result，
       就会拿着上一轮的 passed=False 判成 "retry"，把已经失败的 State 再喂回 Knowledge，
       如此往复直到撞上 LangGraph 的 recursion_limit。

    2. reflection_result is None → 抛 MissingReflectionResultError
       不能静默当成 PASS。走到这条边就说明 reflection 节点跑过了，它没写回结果只能是
       图接错了 —— 按仓库的既有风格，这类不变量被破坏时直接抛（见
       KnowledgeAgent.execute 的 NotAToolCallError、ReflectionReviewer.run 对
       ValidationError / EvidenceReferenceError 的处理）。

    3. 其余按 passed 分流：True → "pass"，False → "retry"。

    **没有重试上限**：iteration_count 由 prepare_retry 累加，但本函数不检查它 ——
    State 里没有「最多重试几次」这个字段，本轮也不改 Schema（见 CHANGELOG 说明）。
    目前唯一的兜底是 LangGraph 自带的 recursion_limit（默认 25），超了会抛
    GraphRecursionError。要真正限次，得让 State 多一个 max_iterations，或在这里比一个
    模块级常量 —— 两条路都要先定 Schema，所以留给你决定。
    """
    if state.status == "failed":
        return "failed"

    if state.reflection_result is None:
        raise MissingReflectionResultError(
            "路由要求 reflection_result 非空，但它是 None："
            f"process_id={state.process_id!r}, status={state.status!r}"
        )

    return "pass" if state.reflection_result.passed else "retry"


def prepare_retry(state: KnowledgeProcessState) -> KnowledgeProcessState:
    """为重试准备 State：只把 iteration_count 加一，返回新对象。

    只做这一件事，因为职责是分开的：

        route_after_reflection  决定「去哪」
        prepare_retry           修改「State」
        knowledge_node          真正「再跑一轮 Knowledge」

    不在这里调 KnowledgeAgent —— 那会把「准备」和「执行」揉在一起，重试轮次也就
    记不清了。不改 proposal / evidence / reflection_result：下一轮 Knowledge 会重写
    proposal，而 reflection_result 得留着 —— build_context 正是靠它把上一轮的审查
    意见交给 Agent 的，清掉就等于让 Agent 闭着眼睛重跑一遍。
    """
    return state.model_copy(
        update={"iteration_count": state.iteration_count + 1}
    )


def build_workflow(
    owner: str,
    repo: str,
    *,
    llm: LLMClient | None = None,
) -> CompiledStateGraph:
    """建好并编译「initialize → knowledge → reflection → retry/pass」这张图。

    owner / repo 在这里给定，就定死了这一轮研究的是哪个仓库 —— KnowledgeAgent 的
    source 由这两个值拼出来（https://github.com/{owner}/{repo}），initialize_state()
    用的正是它。

    llm 是整个图共用的一个实例，在这里解析一次（省略时按 .env 现建）：两个节点都需要
    它，各建一个既浪费也没必要。测试传 FakeLLM 即可全程不碰网络。

    返回值怎么用 —— 注意 LangGraph 的输入必须是**完整合法**的 State：

        wf = build_workflow("example", "demo-project", llm=llm)
        final = wf.invoke(seed)      # final 是 dict，不是 KnowledgeProcessState

    seed 需要一个 process_id / source / status 俱全的 KnowledgeProcessState。这一点
    确实别扭：initialize 节点会**整个替换**掉传进来的 State —— 它调的是现成的
    initialize_state()，那个方法自己生成新的 process_id、自己拼 source，不接收也不
    沿用入参。所以 seed 只是为了满足 LangGraph「输入必须合法」这条校验，**它的 source
    会被忽略**，真正研究哪个仓库由上面的 owner/repo 参数说了算。两者不一致时以参数
    为准，且不会有任何提示。

    iteration_count 不在 build 时设上限：State 里没有对应字段，见 route_after_reflection。
    """
    # 只解析一次：两个节点共用同一个 client。
    resolved = create_llm_client() if llm is None else llm

    def _initialize(state: KnowledgeProcessState) -> KnowledgeProcessState:
        """新建 State：固定采集 metadata + README。

        入参 state 被整个丢掉 —— 见 build_workflow 的说明。这里不重新实现初始化，
        只是把现成的 initialize_state() 接到图上。
        """
        return KnowledgeAgent(owner, repo, llm=resolved).initialize_state()

    def _knowledge(state: KnowledgeProcessState) -> KnowledgeProcessState:
        return knowledge_node(state, llm=resolved)

    def _reflection(state: KnowledgeProcessState) -> KnowledgeProcessState:
        return reflection_node(state, llm=resolved)

    graph = StateGraph(KnowledgeProcessState)

    graph.add_node("initialize", _initialize)
    graph.add_node("knowledge", _knowledge)
    graph.add_node("reflection", _reflection)
    graph.add_node("prepare_retry", prepare_retry)

    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "knowledge")
    graph.add_edge("knowledge", "reflection")

    graph.add_conditional_edges(
        "reflection",
        route_after_reflection,
        {
            "pass": END,
            "retry": "prepare_retry",
            "failed": END,
        },
    )

    # 回到 knowledge，且复用同一个 State —— 不经过 initialize。
    graph.add_edge("prepare_retry", "knowledge")

    return graph.compile()
