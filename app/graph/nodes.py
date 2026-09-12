"""Graph 层的节点 (node)。

职责只有一件：把已有组件接到 State 上，让它们能被当成「一步」来调用。

    knowledge_node    State → KnowledgeAgent.run_once   → State（含 proposal）
    reflection_node   State → ReflectionReviewer.run    → State（含 reflection_result）

节点是「一步」，不是循环。Tool Calling Loop 仍然只在 KnowledgeAgent.investigate()
里；「审查不过 → 回喂 Issue → 重新提案」的外层循环不在这里 —— 那是 workflow 的事，
本模块不实现它，也不实现任何路由。

两个节点都是普通可调用对象，不 import langgraph：LangGraph 的节点就是「收 State、
返回 State 更新」的函数，注册上去即可。项目目前也没装 langgraph（见 requirements.txt），
所以这里不引入这个依赖 —— 写了也用不上，还会让测试多背一个包。

装配方式统一为「llm 关键字注入，省略时按 .env 现建」：

    graph.add_node("knowledge", knowledge_node)     # 走默认：create_llm_client()
    knowledge_node(state, llm=FakeLLM(...))         # 测试：不碰网络

之所以不是「注入 agent 实例」：节点的入参是 State，State 里已经有 source（藏着
owner/repo），再要求调用方另建一个 Agent 传进来，等于把同一份信息拆到两个地方维护。
"""

from ghrepo import GHRepo

from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.reflection import ReflectionReviewer
from app.graph.state import KnowledgeProcessState
from app.llm import create_llm_client
from app.llm.client import LLMClient
from app.logging import get_logger

logger = get_logger("graph.nodes")


def knowledge_node(
    state: KnowledgeProcessState,
    *,
    llm: LLMClient | None = None,
) -> KnowledgeProcessState:
    """调查 + 生成提案，返回写入了 proposal 的新 State。

        State → KnowledgeAgent.run_once → State(proposal, status="analyzing")

        实际做的是 initialize_state 之后的全部两步：
        investigate（Tool Calling Loop）→ generate_proposal。

    只做这一步：不采集（采集是 initialize_state 的事，见下）、不反思、不落库、
    不建关系。run_once() 进入时会把 tool_call_count 归零，所以同一个 State 被
    再喂一次不会因为上次用掉的额度而提前停手。

    owner/repo 从 state.source.url 反解 —— State 里没有单独的 owner/repo 字段，
    而 url 就是 KnowledgeAgent 自己按 owner/repo 拼出来的，这是一条往返的解析。
    用 ghrepo 而不是手写 split：和 main.py 的入口解析同一套规则，残缺地址会
    直接抛 ValueError 而不是静默产出垃圾值。

    失败不抛错：run_once() → generate_proposal() 在 LLM 输出不合法、引用了不存在
    的 Evidence 编号、或压根没有 Evidence 时，返回的是 status="failed" 的新 State
    （这是仓库既有约定，见 knowledge_agent._failed）。这些失败态原样传给下游，
    由它们自己决定怎么办。

    另外：本节点不含采集。一个只有 process_id + source 的空 State 进来是跑不出
    提案的（没有 Evidence）。要完整链路得先过 initialize_state()，把它接到
    workflow 里时注意这一点。
    """
    owner, repo = _owner_and_repo(state)
    # 「第几轮」只有在这里看得见：iteration_count 由 workflow 的 prepare_retry 累加，
    # 而节点本身不碰它。重试回路因此不必自己记一条日志 —— 下一轮开始时会说。
    logger.info(
        "knowledge 节点：开始第 %d 轮调查（process_id=%s，已用 Tool %d 次）",
        state.iteration_count,
        state.process_id,
        state.tool_call_count,
    )

    agent = KnowledgeAgent(owner, repo, llm=_resolve_llm(llm))
    result = agent.run_once(state)

    logger.info(
        "knowledge 节点完成：status=%s，proposal=%s",
        result.status,
        "有" if result.proposal is not None else "无",
    )
    return result


def reflection_node(
    state: KnowledgeProcessState,
    *,
    llm: LLMClient | None = None,
) -> KnowledgeProcessState:
    """审查提案能否被 Evidence 支持，返回写入了 reflection_result 的新 State。

        State → ReflectionReviewer.run(proposal, evidence) → State(reflection_result)

    只做这一步，而且是「只读 + 写回」：proposal 与 evidence 都原样不动，传进去
    什么样出来还是什么样（ReflectionReviewer 自身也保证不改它们）。写回的只有
    reflection_result 与 status。

    status 落成 "reflecting" —— 本节点就是状态机里 reflecting 那一段，这一步做完
    了，它就该标成这样。**不**根据 passed 决定往 "persisting" 还是回头再走一遍：
    那是路由，路由看的是 reflection_result.passed，不该由「执行反思」这个动作
    顺手替它做主。

    state.proposal 为 None 时无法反思（没有可审的对象），落成 failed 而不是抛错 ——
    和 generate_proposal() 在「没有 Evidence」时的处理一致：这属于可预期的域内
    条件，不是代码 bug。注意这时**不**动 proposal / evidence / reflection_result，
    只改 status 与 error。

    LLM 输出过不了 schema 校验（ValidationError）、或引用了不存在的 Evidence 编号
    （EvidenceReferenceError）时**直接抛出**，不兜成 failed State —— 这是
    ReflectionReviewer 的既有约定（ReflectionResult 里没有 error 字段，无处安放
    失败态），而且这两类异常都说明 LLM 的输出该被看见，不该被吞掉。

    不必单独防「evidence 为空」：proposal 非空就说明 generate_proposal() 过了，
    而它要求 evidence 非空。两者不会同时出现。
    """
    if state.proposal is None:
        logger.warning(
            "reflection 节点：没有 KnowledgeProposal 可审，落成 failed"
            "（process_id=%s）",
            state.process_id,
        )
        return state.model_copy(
            update={
                "status": "failed",
                "error": "没有 KnowledgeProposal，无法反思",
            }
        )

    reviewer = ReflectionReviewer(_resolve_llm(llm))
    result = reviewer.run(state.proposal, state.evidence)

    # passed 那个结论不在这里重复记 —— ReflectionReviewer 已经记过，而它拿得到
    # issues（更完整）。同一件事实只在能拿到最多信息的那一层说一次。
    return state.model_copy(
        update={"reflection_result": result, "status": "reflecting"}
    )


def _resolve_llm(llm: LLMClient | None) -> LLMClient:
    """省略 llm 时按 .env 现建一个。

    不写成 `llm or create_llm_client()`：那要看对象的真值，而 LLMClient 是个
    Protocol，是否定义 __bool__ 由实现方决定 —— 一个「空」的 fake 会被悄悄换成
    真实客户端，测试就跑去发网络请求了。
    """
    return create_llm_client() if llm is None else llm


def _owner_and_repo(state: KnowledgeProcessState) -> tuple[str, str]:
    """从 state.source.url 反解 (owner, repo)。

    GHRepo 的字段叫 name 不叫 repo，别顺手写错（main.py 里提过同一个坑）。
    """
    try:
        ref = GHRepo.parse(state.source.url)
    except ValueError as error:
        raise ValueError(
            f"无法从 source.url 解析出 owner/repo：{state.source.url!r}（{error}）"
        ) from error

    return ref.owner, ref.name
