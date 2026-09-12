# new-ai-insight-agent 版本记录

## [1.0.11] - 2026-09-11

## 日志模块（app/logging.py）
- 新增 `app/logging.py`：`get_logger(name)` / `configure_logging(settings=None, *, level=None, stream=None)`，用标准库 `logging`，**不引任何第三方日志库**
- 定位是**调试追踪**而不是审计流：单行文本、时间只到秒（`datefmt="%H:%M:%S"`）、默认写 **stderr**。stdout 留给 `main.py` 的中文报告 —— 那是运行结果，日志是过程，混在一起就没法 `python main.py > out.txt` 了
- logger 名分层：`get_logger("agent.knowledge")` → `ai_insight.agent.knowledge`，一条 `AI_INSIGHT_LOG_LEVEL` 设在 `ai_insight` 这一层就控制全部（子 logger 的 level 都是 `NOTSET`，向上继承）。**刻意不用 `__name__`**：那样树根会叫 `app`、名字里还带着文件名，看不出「哪一层在说话」。粒度约定是「一个模块一个 logger」，不要细到函数
- 级别**必须设在 logger 上**，不能只设 handler 的级别：级别检查发生在记录进入任何 handler **之前**，未 configure 时 `ai_insight` 的 effective level 继承 root 的 `WARNING`，INFO 会被提前丢掉，handler 再宽松也收不到
- **幂等**：重复 `configure_logging` 只摘掉自己装过的 handler（靠 `_OWN_HANDLER_MARK` 标记属性识别）再装新的，不会叠加。**刻意不用 `logger.handlers.clear()`**—— pytest 的 handler、宿主程序自己加的都挂在同一棵树上，clear 会把它们一起干掉，表现为「测试里的日志断言莫名消失」。也**不调 `logging.basicConfig()`**：它动的是 root，且 root 已有 handler 时静默什么都不做，格式就悄悄不生效了
- `configure_logging` **自己不读 env**：默认级别是常量 `INFO`，要按 .env 配就由调用方传 `load_log_settings()`（`main.py` 那一行）。读 env 的只有 `load_*_settings`，装配的只有 `configure_*` —— 和 `load_llm_settings` / `create_llm_client` 的分工一致。这样测试里 `configure_logging(level="DEBUG")` 就是全部，不必 monkeypatch 环境变量，也不会因为某台机器 `.env` 写了 `AI_INSIGHT_LOG_LEVEL=DEBUG` 而让断言忽明忽暗
- 静音靠 `level="CRITICAL"`（本项目不打 CRITICAL，等于关掉），不再加一个 `enabled` 开关 —— 少一个概念
- 默认用 `sys.stderr` 时顺手 `reconfigure(encoding="utf-8", errors="replace")`：中文日志撞上 GBK 控制台会抛 `UnicodeEncodeError`，被 logging 自己的异常处理吞成一行 `--- Logging error ---`。与 `main.py` 对 stdout 的处理同一个理由、同样先 `hasattr`（pytest 会换掉 `sys.stderr`）。调用方显式传了 `stream` 就不碰全局
- 文件名叫 `logging.py` **不产生遮蔽**：绝对导入（PEP 328）下 `app/` 里任何 `import logging` 拿到的都是标准库（本模块第一行也正是它）。唯一能遮蔽的场景是「在 `app/` 目录里跑脚本」，本项目两个入口都从项目根跑。先例：`flask/logging.py`
- 级别名清单写死在 `config.LOG_LEVELS`，不用 `logging.getLevelNamesMapping()` —— 那个 3.11 才有，本项目是 3.10
- 抓日志不需要自定义 handler：`configure_logging(stream=io.StringIO())` 就够，测试因此走的是公开 API

## 打点接入（6 个文件）
- 级别的一致原则：**INFO** = 运行轨迹的骨架，默认可见（删掉这行就看不出发生了什么）；**WARNING** = 轨迹完整，但信息/能力被丢掉（降级、截断、达到上限、失败态、LLM 乱指名 Tool）；**DEBUG** = 排障才需要的细节；**ERROR 不用** —— 异常一律上抛，traceback 自带完整信息，再记一条等于把同一次失败说两遍
- 另一条是**去重**：同一件事实只在能拿到最多信息的那一层打一次
- `tools/registry.py`（Tool 执行的唯一收口点，所以只在这里打一处，不逐个 Tool 文件打）：调用前 INFO 记 Tool 名 + 参数 + 仓库；未知 Tool 与两处参数校验失败在 raise 前各留一条 WARNING；`owner/repo` 被 State 覆盖是刻意的，但 LLM 到底写了什么值得留痕（DEBUG，且**必须在覆盖之前**判断，覆盖之后就看不出来了）
- `agents/knowledge_agent.py`：每轮决策 INFO（同时带内层 `tool_call_count + 1` 和外层 `iteration_count` —— 两个计数说的不是一回事）、Tool 结果入库 INFO（记的是转换成 Evidence 之后的样子）、finish INFO、**撞上 `MAX_TOOL_CALLS` 仍未 finish 记 WARNING**、提案成功 INFO、`_failed()` 里 WARNING（一处覆盖「没有 Evidence / LLM 输出不合 `ProposalDraft` / 引用了不存在的 Evidence 编号」三条失败路径）；`run_once()` 归零 `tool_call_count` 时补一条 DEBUG（只在真的归零了才记，首轮没额度可归、记了是噪音）
- **撞上限那条 WARNING 是本轮最有价值的一处**：撞上限和「LLM 说够了」在 State 上长得一模一样（都是 `status="collecting"`），在此之前二者无法区分，而它正是「这份提案为什么没查透」的答案
- `agents/reflection.py`：`passed=True` INFO、`passed=False` WARNING 并列出 issue 类型（那是重试的待办清单）。**`ValidationError` / `EvidenceReferenceError` 两条路径刻意不打点** —— 它们按设计直接抛（`ReflectionResult` 里没有 error 字段，无处安放失败态），异常一路冒到调用方、信息完整；为打点在外面包一层 `try/except ... raise` 会改变代码形状，并在「不吞异常」的既有约定旁边开一个口子
- `graph/nodes.py`：`knowledge_node` 开始/完成各一条 INFO。**「第几轮」只在这里看得见** —— `iteration_count` 由 `workflow.prepare_retry` 累加，重试回路因此不必自己记日志，下一轮开始时会说。`reflection_node` 只在 `proposal is None` 落成 failed 时记 WARNING（`passed` 那个结论已在 `ReflectionReviewer` 里记过，且那边拿得到 issues）
- `llm/openai_compatible.py`：三档降级每退一档记一条 WARNING（从哪档退到哪档 + 服务端原文压成一行、截前 200 字符）。**降级在此之前完全不可见**，而它正好解释了「为什么模型偶尔吐回需要 `_extract_json` 抠的文本」。每个进程只记一次（`_mode` 会记住，之后不再试探），符合它「一次性能力损失」而非「每次调用的噪音」的性质
- `graph/context.py`：整段 Context 超长被截断记 WARNING（次数少、后果重 —— 后面的 Evidence LLM 完全看不到）；单条 Evidence 正文被截断记 DEBUG（真实 README 动辄上万字符，几乎必然触发，放 INFO 会把轨迹骨架淹掉）。两处都在 `_render_evidence*` 里，两个 Context 入口共用同一个截断点，所以日志不会重复实现
- **`app/graph/workflow.py` 刻意不打点**：`prepare_retry` 想记的「iteration_count 0 → 1」已被 `nodes.knowledge_node` 覆盖，轨迹里不会留下空洞（`retry` 必有下一轮 knowledge、`failed` 必有 `_failed` 的 WARNING、`pass` 必有 `ReflectionReviewer` 的通过行）。`route_after_reflection` 因此保持纯函数 —— 它 docstring 明写「不改 State、不调 Agent、不调 LLM」，打点会引入全局可观察副作用，而它恰好承担着「failure 优先于 reflection_result」「None 要抛不要当 PASS」两条最易写错的不变量
- 所有打点**只读不写**（`sorted(...)` / `len(...)` / 列表推导都是新建对象，没有一处对 state 或 arguments 赋值），也不打整份 `state`（pydantic 的 repr 虽无副作用，但会把整份 Evidence 写进 stderr），更不触发 LLM / Tool —— 所以「传入的 state 不会被修改」那批既有断言、以及「数 `llm.calls`」「数 evidence 条数」全部继续成立

## 环境变量
- 新增选填的 `AI_INSIGHT_LOG_LEVEL`（DEBUG / INFO / WARNING / ERROR / CRITICAL，默认 INFO），`.env.example` 已补。**名字带 `ai_insight_` 前缀是刻意的**：`LOG_LEVEL` 太通用，Docker / K8s / 各家 PaaS 的环境里可能已经有一个同名但管着别的东西的变量，而真实环境变量优先于 `.env`（`load_dotenv(override=False)`），撞上了会静默按别人的值走、日志级别莫名其妙。变量名收敛在 `config.LOG_LEVEL_ENV_VAR` 一处，`main.py` 与测试都引它，不写字面量
- 与其他变量不同，**它不做必填检查**：没写 `.env`、甚至 `.env` 不存在（CI 就是），都回落到 INFO —— 日志级别猜一个总比「连日志都起不来」好。`_REQUIRED_ENV_VARS` 那条纪律要解决的是「缺了就跑不动的东西」，这里不适用
- `LogSettings` / `load_log_settings()` 放在 `app/config.py`，与 `LLMSettings` / `load_llm_settings()` 同一形状；级别名归一化（`normalize_log_level()`）也放在那里，因为 `app/logging.py` 的 `_coerce_level()` 要复用它 —— 放 `logging.py` 会让两个模块互相 import。**大小写不敏感**是刻意的（`.env` 里写小写是常态），而 `Logger.setLevel()` 只认大写精确匹配
- `main.py` 只在入口加一处 `configure_logging(load_log_settings())`；级别写错不拖垮整次运行，退回默认级别并说一声。**既有 12 处 `print` 一字未动** —— 那是对齐的中文报告，是「运行结果」，不是过程日志

## 测试（tests/test_logging.py）
- 新增 18 条测试：装配（幂等、不碰别人的 handler、默认不读 env、CRITICAL 静音、大小写、未知级别被拒、`get_logger` 无副作用）+ 接入点（Tool 调用、未知 Tool、每轮决策、撞上限、反思通过与未通过、两层截断、三档降级）+ 一条不变量（同一份 State 在 CRITICAL 与 DEBUG 下跑出的结果完全相同）
- **不建 `conftest.py`、不加 fixture、不用 `caplog`**，与既有测试一致。用 `configure_logging(stream=io.StringIO())` 抓日志：`caplog` 抓的是 root（我们的日志挂在 `ai_insight` 上，多一个隐含前提），且 `caplog.set_level` 会改 logger 级别，恰好和「幂等」「默认级别」两组断言打架
- **刻意不测 `load_log_settings`**：它内部调 `load_dotenv`，而那个函数直接往 `os.environ` 写值（不经过 monkeypatch），一测就会污染整个测试进程，破坏本仓库「测试不碰 `os.environ`」的性质。既有先例一致 —— `load_llm_settings` 至今也没有测试
- 全量 90 passed（原 72 + 新 18）

## [1.0.10] - 2026-09-11

## KnowledgeAgent.run_once()
- 抽出 `run_once(state)`：只跑「investigate → generate_proposal」两步，接收已有 State、返回新 State，调用方因而可以拿它当一个节点用
- `run()` 改为 `initialize_state() + run_once()`，行为不变（仍是采集 → 调查 → 提案）
- `run_once()` 进入时把 `tool_call_count` 归零：同一个 State 被重复处理时，上一次用掉的额度不该继续占着，否则第二轮 `investigate()` 会直接停在 0 次调用。这一条正是后面 `workflow` 重试回路的前提
- 不含任何循环与路由，循环仍只在 `investigate()` 里

## Graph 层节点（app/graph/nodes.py）
- 新增 `app/graph/nodes.py`，把已有组件接到 State 上，让它们能被当成「一步」来调用：
  - `knowledge_node`：`State → KnowledgeAgent.run_once → State(proposal, status="analyzing")`
  - `reflection_node`：`State → ReflectionReviewer.run → State(reflection_result)`
- 节点是「一步」不是循环：Tool Calling Loop 仍在 `KnowledgeAgent.investigate()` 里，重试与路由都不在这个模块
- **不 import langgraph**：LangGraph 的节点本就是「收 State、返回 State 更新」的函数，写了也用不上（本版之前项目还没装 langgraph），没必要让它背一个包
- 装配方式统一为「llm 关键字注入，省略时按 .env 现建」：`node(state)` 仍是合法调用，测试传 `FakeLLM` 即可全程不碰网络。没有做成「注入 agent 实例」—— 节点的入参是 State，State 里已经有 source，再要求调用方另建一个 Agent 传进来，等于把同一份信息拆到两个地方维护
- `knowledge_node` 从 `state.source.url` 反解 owner/repo（走 `ghrepo`，与 `main.py` 同一套规则）。用手写 split 对残缺地址会静默产出垃圾值（见 1.0.9），这里不重蹈
- `knowledge_node` **不含采集**：`run_once()` 是 `initialize_state()` 之后的两步。一个只有 `process_id + source` 的空 State 喂进去会落成 `failed`（没有 Evidence，`generate_proposal()` 的既有约定），接图时必须先过 `initialize_state()`
- `reflection_node` 的 status 落成 `"reflecting"`，**不**按 `passed` 前进到 `persisting` 或回头重跑 —— 那是路由的事。路由看 `reflection_result.passed`，不该由「执行反思」这个动作替它做主
- 失败处理分两类：`proposal is None` 时落成 `failed` 而不抛错（这是可预期的域内条件，与 `generate_proposal()` 在「没有 Evidence」时的处理一致）；LLM 输出过不了 schema 校验或引用了不存在的编号则**直接抛**（沿用 `ReflectionReviewer` 的约定 —— `ReflectionResult` 里没有 error 字段，无处安放失败态，而且这两类异常都说明 LLM 的输出该被看见）

## Reflection 结果回喂 Knowledge Agent
- 此前反馈是断的：`reflection_node` 把结果写回 `state.reflection_result` 之后就没有下文，而 `build_context()` 只渲染 evidence，Agent 根本看不见审查意见。这一节把这条通路接上
- `graph/context.py` 的 `build_context()` 改为按固定顺序渲染三段：**Evidence → Previous Proposal → Reflection Result**，后两段仅在对应字段非空时追加
  - 首轮 `proposal` 与 `reflection_result` 皆为 `None`，渲染结果与从前完全一致 ——「首轮行为不变」不需要额外的开关来保证
  - 顺序是刻意的：证据在前，Agent 读到的第一件事仍然是事实；提案与反思在后，以「上一轮的结论，待修正」的姿态出现
  - Evidence 段**复用** `_render_evidence_list()`，没有内联：截断与编号规则只该有一处，`build_reflection_context()` 也在用同一个函数
  - Proposal 与 Reflection 段内嵌的 Evidence 正文压成 `location`（复用 `_citations`）：正文在 Evidence 段已逐条列过，重复三遍会把 Agent 的上下文挤满，反而看不见新证据
  - 长度上限只作用在 Evidence 上；Proposal 与 Reflection **不截断** —— 前者是待修正的对象，后者是必须逐条处理的行动清单，截了会让 Agent 把「没看到」当成「不存在」，漏掉该补的证据
  - 新增 `_render_reflection_result()`：`description` / `passed` / `summary` 原样保留（那是反馈的主体，压缩它就等于把反馈本身弄丢），只有 `evidence` 压成 location
- `agents/prompts.py` 为两条 Agent 提示词各加「如果这是一次重跑」一节：
  - `DECISION_SYSTEM_PROMPT`：Context 里出现这两段时，把 issues 当作**优先级最高的信息缺口**，优先选能补上它的 Tool（`search_code` 定位 → `get_file` 读实现），不要因为「上一轮已调查过」就跳过 —— 上一轮的 Evidence 支撑不住那个结论才会被审查出来
  - `PROPOSAL_SYSTEM_PROMPT`：逐条处理 issue，按 `factual_error` / `unsupported_claim` / `missing_evidence` / `contradiction` 四类分别处置，明说**不要原样重复上一版**（那等于这轮重跑没有发生）
  - 两节都是**条件生效**：「没有这两段（第一次跑），或者 issues 为空时，忽略本节」。所以接入 Reflection 之后首轮行为仍然完全不变
  - `REFLECTION_SYSTEM_PROMPT` 一个字未动
- `build_reflection_context()` 保持原样 —— 那是 **Reviewer 自己的输入**（Proposal 在前、Evidence 在后，且 Proposal 不截断），与回喂给 Agent 的这条路是两件事，合并不但没必要，还会同时破坏「先看结论再核依据」和「先看事实」这两个刻意的顺序
- 因为 `build_context()` 被 `decide()` 与 `generate_proposal()` **两处**共用，接通后**调查决策**和**提案生成**都能看见反馈：`decide()` 可以据此挑一个 Tool 去补缺口

## LangGraph 外层流程（app/graph/workflow.py）
- 新增 `app/graph/workflow.py`，把 `initialize → knowledge → reflection → retry/pass` 串起来：
  - `build_workflow(owner, repo, *, llm=None)`：组装并 `compile()`。`llm` 在 build 时解析一次，两个节点共用同一个实例
  - `route_after_reflection(state)`：纯路由，返回 `"pass"` / `"retry"` / `"failed"`。不改 State、不调 Agent、不调 LLM、不执行循环
  - `prepare_retry(state)`：只做 `iteration_count += 1`，返回新对象
  - `MissingReflectionResultError`：走到路由时 `reflection_result` 仍为 `None` 时抛（仓库存量风格：`NotAToolCallError`、`EvidenceReferenceError` 也是模块级 `RuntimeError`）
- 职责按「决定去哪 / 修改 State / 真正执行」三分：`route_after_reflection` 决定去哪，`prepare_retry` 只改 State（**不**在这调 KnowledgeAgent，否则重试轮次就记不清了），`knowledge_node` 真正再跑一轮
- **循环靠 conditional edge 构成，代码里没有 while**
- **重试复用同一个 State**：路径是 `reflection → prepare_retry → knowledge`，`prepare_retry` 只动 `iteration_count`，**不清 `reflection_result`**（清了 `build_context` 就交不出反馈，Agent 等于闭眼重跑），更不回头调 `initialize_state()` —— 那会新建 `process_id` 与空 evidence，上一轮的证据全丢，而 Issue 恰恰要靠这些证据解决
- **路由必须先看 `status` 再看 `passed`，否则死循环。** 这条路径实际可达，不是理论风险：
  ```text
  第 1 轮: knowledge 成功 → reflection 判 passed=False          （reflection_result 留下，passed=False）
  第 2 轮: knowledge 失败 → status="failed"，proposal=None
                             但 _failed() 只把 proposal 置回 None，不动 reflection_result
          → reflection_node: proposal 为 None，直接返回，不调 LLM、也不改 reflection_result
          → status="failed" 与上一轮的 passed=False 同时在手
  ```
  若先看 `passed` 就会判成 `"retry"`，把已失败的 State 再喂回 Knowledge，往复直到撞上 `recursion_limit`
  → 因此路由多了一条 `"failed": END` 边。失败态作为**数据**交给调用方，与 `main.py` 先看 `status`/`error`、`generate_proposal()` 失败不抛错的既有约定一致
- 真正的语义边界：不落库、不建关系、不做 embedding、不实现 Relation Agent、不改 proposal / evidence。Reflection 判 pass 只是「提案站得住」，**不代表已经持久化**

## 依赖
- `requirements.txt` 新增 `langgraph>=1.2`（实测 1.2.11）。此前未装，`workflow.py` 无法 import
- 顺带补上 1.0.9 遗留的 `.venv` 缺包：`ghrepo` 装了但没装全（走的是同一条 `pip install -r requirements.txt`）

## tests
- **本版未新增测试**，全量仍 72 passed（`context.py` / `prompts.py` 的改动没有破坏任何既有测试，`build_context()` 的首轮行为也由「首轮 = 只有 Evidence」这一实测确认未变）
- 已做的人工验证（临时脚本，未落盘）：
  - `build_context`：首轮只渲染 Evidence 且编号从 1 起；重跑时三段齐全、顺序正确；Proposal / Reflection 段内嵌证据只留 location、正文不重复；截断只作用于 Evidence
  - 反馈闭环：`knowledge → reflection(FAIL) → knowledge` 重跑时，`decide()` 的 prompt 里确实出现了 `## Previous Proposal`、`## Reflection Result`、Reviewer 的问题描述与问题类型
  - `workflow`：PASS 路径 `iteration_count=0`；RETRY 路径 `iteration_count=1` 且 **evidence 条数不变**（证明没重建 State）、重跑时能看到反馈；FAILED 路径正确停在 END 不死循环；`route_after_reflection` 四种输入（passed / 非 passed / status=failed / None 抛错）逐一验过；`prepare_retry` 只动 `iteration_count`、不碰 evidence 与 reflection_result、不改入参
- **仍未验证**：全程用 `FakeLLM`，脚本写什么就出什么。所以「真实 LLM 能否审出问题」「能否照着重跑段去补证据」都没有被验证 —— 这两件需要真实 LLM 客户端跑一遍才算数（1.0.9 也留了同样的缺口）

## 待接
- **重试没有上限。** `iteration_count` 由 `prepare_retry` 累加，但 State 里没有「最多几次」这个字段，本版**未改 Schema**。若 LLM 一直判 `passed=False` 就会一直重跑，目前唯一兜底是 LangGraph 自带的 `recursion_limit`（默认 25），超了抛 `GraphRecursionError`。要真正限次有两条路，都要先定 Schema：State 加 `max_iterations`（语义完整、可配置），或 `workflow.py` 里比一个模块级常量（不动 Schema，但配置散在图里）
- **`build_workflow` 的 seed State 有点别扭。** LangGraph 的输入必须是合法完整的 State（`process_id` / `status` 必填，实测只给 `source` 会 `ValidationError`），而 `initialize_state()` 是**构造器不是变换器** —— 它自己生成 `process_id`、自己按 owner/repo 拼 source，不接收也不沿用入参。所以调用方为满足校验传的 seed 会被整个丢掉，**seed 的 source 被静默忽略**：研究哪个仓库由 `build_workflow` 的参数决定，两者不一致时没有任何提示。这是目前最容易踩的坑
- `app/graph/__init__.py` 未导出 `nodes` / `workflow`，调用方目前从 `app.graph.workflow` 直接 import
- `app/graph/node.py`（单数）是个空的未跟踪文件，与本版的 `nodes.py` 容易混，未处理
- `main.py` 仍是单轮 `agent.run()`，没有接 `build_workflow()`；`Workflow` 目前只有测试/脚本在调
- 未实现（设计文档范围之外）：Relation Agent、数据库持久化、pgvector / Embedding、RAG、API、多 Agent

## [1.0.9] - 2026-09-10

## Reflection（Evidence-grounded Reviewer）
- 新增 `app/agents/reflection.py`：`ReflectionReviewer(llm).run(proposal, evidence) → ReflectionResult`。职责只有一件 —— 检查 KnowledgeProposal 里的事实性内容能否被已有 Evidence 支持
- 范围上它是 `generate_proposal()` 的镜像：那个是「Evidence → 提案」，这个是「提案 + Evidence → 审查」。两者的输入都只有数据、输出都只有结构，都不碰 Tool
- **它不是 Agent**，也不该长成 Agent：不持有 Tool、不调 Tool、不做 Tool Calling Loop、不获取新 Evidence（不去外面找）、不修改也不重新生成 Proposal、不决定下一步 Workflow。证据不足时只记录 Issue，把 Issue 反馈给 Knowledge Agent 是外层 Workflow 的事（本阶段不实现）
- `llm` 必填，没照抄 `KnowledgeAgent` 的 `llm=None` 可选写法 —— 那个可选的依据是「采集阶段不需要 LLM」，这个理由在 Reflection 不成立（它从头到尾只有「问 LLM」这一件事）
- 输入只要 `KnowledgeProposal` + `list[Evidence]`，**不接 State**（设计文档明确要求，不把整个 State 传给 LLM）
- 不写回 `state.reflection_result`（本次只实现 Reflection 本体，写回属于外层 Workflow）
- 新增 `REFLECTION_SYSTEM_PROMPT`：逐项检查 title / summary / problem / core_features / technologies / architecture / learning_points；语义等价即算得到支持（不要求逐字一致）；明确「不要过度挑刺，你不是语法检查器」；明确「Evidence 不足时宁可 FAIL，不要用你自己的知识补缺口」
- Prompt 里**不提 `low_quality`**：`IssueType` 枚举里有它，但设计文档的判定标准只用四种（factual_error / unsupported_claim / missing_evidence / contradiction），所以不引导 LLM 去用。枚举本身未动
- 「某个 claim 该判哪一类 Issue」完全由 LLM 判断，代码不做二次推断（有测试钉住）

## Reflection 的 Evidence 引用（LLM 不许填 Evidence 正文）
- 新增 `schemas/reflection.py` 的 `DraftReflectionIssue` / `ReflectionDraft`：LLM 侧的输出结构，与 `ReflectionResult` 只差一处 —— `issues[].evidence` 是 `list[int]` 编号而不是 `list[Evidence]`。**现有 `ReflectionIssue` / `ReflectionResult` 未做任何改动**
- 为什么不让 LLM 直接输出 `ReflectionResult`：那个 schema 的 evidence 是完整 `Evidence` 对象，四个字段全是自由文本，LLM 完全可以写出一份输入里根本不存在的证据，而 schema 一个都校验不出来。Reflection 的价值就在于「结论可回溯到证据」，那样就没了 —— 和 `ProposalDraft` 挡掉的是同一类问题，只是后果更严重
- 新增 `app/graph/reflection.py`：`build_reflection_result(draft, evidence)` —— 纯函数，把编号换回输入 evidence 的原文。编号从 1 开始（与 context.py 一致），越界**报错而不静默跳过**：编号对不上说明 LLM 在编造引用
- 异常复用 `graph/proposal.py` 的 `EvidenceReferenceError`，不另定义同义异常
- 新增 `graph/context.py` 的 `build_reflection_context(proposal, evidence)`：Proposal 在前（先看结论再核依据）、Evidence 在后；**长度上限只作用在 Evidence 上，Proposal 不截断** —— 提案正是被审查的对象，看一半会让 LLM 把「没截到」当成「不存在」，报出一堆假问题
- Proposal 段里每个字段自带的 evidence 只保留 `location`，正文不重复出现（正文在「可用的 Evidence」段已逐条列过）
- `graph/context.py` 把 `build_context()` 的函数体抽成私有的 `_render_evidence_list()`，两个入口共用 —— 截断规则与编号规则只该有一处，否则「给 LLM 看多少」会随调用点漂移。**`build_context()` 行为零变化**（原 56 个测试全过）
- LLM 输出过不了 schema 校验（`ValidationError`）或引用编号越界时**直接抛出**，不兜成「审查失败」：`ReflectionResult` 里没有 error 字段，没有地方安放失败态。外层 Workflow 怎么处理（重试 / 落成 failed State），等实现它时再定

## 仓库地址解析（改用 ghrepo）
- `main.py` 现在接受 `python main.py [仓库地址 | owner repo]`，支持 `https://github.com/owner/repo`、`git@github.com:owner/repo.git`、`owner/repo` 三种写法
- 解析交给 `ghrepo` 的 `GHRepo.parse()`（`requirements.txt` 新增 `ghrepo>=0.7`，零依赖）。用 `parse()` 而不是 `parse_url()`：前者同时吃 URL 和裸的 `owner/repo`，正好覆盖入口的两种入参形式
- 注意 `GHRepo` 的字段叫 `name` 不叫 `repo`
- **此前手写版本的问题**：先按 `/` 切开取最后两段，对残缺地址会静默产出垃圾数据 —— `https://github.com/` 得到 `owner="https:", repo="github.com"`，`github.com/owner` 得到 `owner="github.com", repo="owner"`，`len(segments) < 2` 那个兜底拦不住（段数是够的，只是前面混进了 scheme 和域名），错值会一路传到 `state.source.url` 和提案标题。ghrepo 对这两种输入直接抛 `ValueError`，现在入口会打印「仓库地址有问题」并以退出码 1 结束
- 已知限制：`ghrepo` 只认纯粹的仓库地址，`https://github.com/owner/repo/tree/main` 这类从子目录页复制的地址会被判为非法（要支持需自己先剥掉 `/tree/` 之后的部分，本次未做）

## 依赖修复
- `.venv` 缺 `python-dotenv` 与 `openai`（`requirements.txt` 里写了但没装），导致 6 个测试文件卡在 collection 阶段、整套测试跑不起来。已 `pip install -r requirements.txt` 补上

## tests
- 新增 tests/test_reflection.py（16）：设计文档第十一节的五个 Test（全通过 / 事实错误 / 无证据 / Evidence 冲突 / 不调 Tool），加装配关系（编号回填的是输入原文，用 `is` 做同一性断言；编号从 1 起；多条 issue 各自回填；Issue 类型原样来自 LLM；用的是 reflection 自己的 prompt；Context 里 proposal 与 evidence 都在）与边界（引用不存在的编号报错、LLM 输出不合法抛 `ValidationError`、Proposal 不参与截断、Proposal 内嵌证据只留出处、不修改传入的 proposal 与 evidence）
- 「不调 Tool」那个测试除了 monkeypatch `call_tool` 让它炸，还断言 `app.agents.reflection` 模块**根本没导入 Tool** —— 证明是「不可能调」而不是「碰巧这条路径没调到」
- 全量 72 passed（原 56 + 新 16）
- 仍未验证：FakeLLM 的草稿是脚本写死的，所以「LLM 能否真正审出问题」没有被验证 —— 判定标准是否好用，需要真实 LLM 客户端

## 待接
- `ReflectionReviewer` 目前只有测试在调，`main.py` 里还没接；`state.reflection_result` 无人写入
- 未实现（设计文档第十二节明确排除）：Knowledge Agent 重试、LangGraph 外层循环、Relation Agent、数据库、Embedding、RAG、新 Tool、多 Agent

## [1.0.8] - 2026-09-10

## 接入真实 LLM（OpenAI 兼容端点 + .env 配置）
- 新增 `app/config.py`：`LLMSettings` + `load_llm_settings()` + `ConfigError`。配置只在这里读、读出来就校验 —— 少一个环境变量在这里报错，而不是等到调 LLM 时冒出一句看不懂的 401；数字写错会点名是哪个变量。真实环境变量优先于 `.env`（`override=False`），部署时好覆盖
- 环境变量：`LLM_API_KEY`（必填）、`LLM_MODEL`（必填）、`LLM_BASE_URL`、`LLM_TIMEOUT`(60)、`LLM_MAX_TOKENS`、`LLM_TEMPERATURE`(0)
- 新增 `app/llm/openai_compatible.py`：`OpenAIClient`，实现 `LLMClient`。任何说 `/chat/completions` 的服务都能接（OpenAI / DeepSeek / 通义 / Moonshot / vLLM / Ollama），换家只改 .env
- 结构化输出三档，从强到弱（`_mode` 记住当前档位，`mode` 属性可查）：
  - ① `json_schema` —— 原生 `response_format={"type": "json_schema", strict: True}`，字段名与类型由服务端保证
  - ② `json_object` —— 只保证「回复是合法 JSON」，schema 写进提示词，字段对不对由 pydantic 判
  - ③ `prompt` —— 连 json_object 都没有：schema 只写在提示词里，拿回来剥掉可能的代码块/前后话再用 pydantic 校验
  - 每档被拒就往下退一档并立刻用新档重试，所以第一次调用最多发三次请求；试通之后停在那里，后续不再白试。三档的差别只在「谁来保证结构」：档 ① 是服务端，档 ②③ 都是 pydantic
  - 降级只在「报错信息里出现 response_format / json_schema / json mode / json_object」时触发；其他 400（比如模型名写错）照抛，不伪装成「降级后仍然失败」
- **实测（DeepSeek）**：DeepSeek 拒绝 `json_schema`，停在档 ② `json_object` —— 它支持 json_object 但不支持自定义 json_schema。所以「让服务端保证字段名」这条路目前走不通，最终仍由 pydantic 兜底
- `_strict_schema()`：把 pydantic 生成的 schema 调成严格模式要的样子（递归补 `required` 列全所有 properties、`additionalProperties: false`）。**不补会直接 400** —— `AgentDecision.tool_name`、`DraftFeature.evidence_refs` 这类有默认值的字段，pydantic 原本不放进 `required`
- `max_tokens` 留空就不传该参数；用 `max_tokens` 而不是 `max_completion_tokens`，前者是各家兼容端点的最大公约数
- `app/llm/__init__.py` 新增 `create_llm_client()`：调用方一句 `KnowledgeAgent(owner, repo, llm=create_llm_client())` 即可，不必知道背后是哪家
- 新增 `.env.example`（模板，提交）与 `.gitignore` 的 `.env` 条目（**此前 .gitignore 里没有 .env，密钥会被提交**）
- 新增 `requirements.txt`：项目此前没有依赖清单

## 提示词调优（实测反馈）
- 真实运行发现 LLM 把 `pyproject.toml` 当成技术写进了 `technologies`（category=other）。文件只能说明「存在这么一个文件」，说明不了选型，属于凭空推断
- `PROPOSAL_SYSTEM_PROMPT` 的「输出结构」里，technologies 的 `name` 补上示例与反例（「例如 Python / FastAPI / PostgreSQL，不是文件名」）
- 「硬性约束」新增第 3 条：technologies 只写语言 / 框架 / 库 / 数据库 / 基础设施 / 模型，文件名、配置文件、目录名一律不算；原第 3~6 条顺延为 4~7
- 另一处待办（**本次未动**）：`core_features` 目前会写成实现细节而不是「项目提供的功能」，粒度偏细

## 入口脚本
- 新增根目录 `main.py`：`KnowledgeAgent(owner, repo, llm=create_llm_client()).run()`，打印 process_id / status / 实际走的档位 / Tool 调用次数 / Evidence 清单，最后把 `state.proposal` 按 JSON 打出来
- 用法 `python main.py [owner] [repo]`，不传参用 `example/demo-project`（底层仍是 mock 数据）
- 两处容易踩的坑在脚本里显式处理了：`.env` 缺配置抛 `ConfigError` 要先接住；`generate_proposal()` 失败是落成 `status="failed"` 而不是抛异常，不能只等异常
- 档位用 `getattr(llm, "mode", "未知")` 取 —— `mode` 是 `OpenAIClient` 的实现细节，不在 `LLMClient` 协议里

## 待接
- `main.py` 是临时入口，`run_knowledge_agent.cpython-313.pyc` 残留的源码仍不在

## [1.0.7] - 2026-09-10

## KnowledgeProposal 生成（generate_proposal）
- 链路补齐：`initialize_state → investigate → generate_proposal`，`KnowledgeProcessState.proposal` 终于有人填了。此前 finish 之后提案无人生成，`status` 永远停在 collecting
- `run()` 改为三段式，自身不含逻辑；原来写死在 run() 里的固定采集挪进新增的 `initialize_state()`（调什么 Tool、什么顺序仍写死，全程无 LLM）
- 新增 `agent.generate_proposal(state)`：Evidence → Context → LLM → 代码回填 → KnowledgeProposal。只做这一件事 —— 不调 Tool、不改 Evidence、不反思、不落库、不建关系
- 字段分工（原则：代码能确定的就不交给 LLM）
  - 代码：`title`（owner/repo）、每条 `evidence` 的正文（按编号从 state.evidence 取原文）
  - LLM：summary / problem / core_features / technologies / architecture / learning_points
- 新增 `schemas/knowledge.py` 的 ProposalDraft / DraftFeature / DraftTechnology / DraftArchitecture：LLM 侧的输出结构，与成品只差两处 —— 没有 title，evidence 是 `list[int]` 编号
  - 为什么不让 LLM 直接输出 KnowledgeProposal：那个 schema 的 evidence 是 `list[Evidence]`（含正文），等于要求 LLM 把证据再写一遍，而 evidence.py 的约定是「Evidence 必须由代码生成」。草稿不是第二套 Proposal，落库仍只有 KnowledgeProposal 一个
- 新增 `graph/proposal.py`：`build_proposal(draft, state, title=...)` —— 纯函数，把编号换回 State 里的原文、补上 title，拼出成品；与 graph/context.py 是同一层的一对（前者 State→文本，后者 LLM 草稿+State→结构）
- 新增 `EvidenceReferenceError`：草稿引用了不存在的编号就报错，**不静默丢弃**（编号对不上说明 LLM 在编造引用，静默丢会让提案带着无法回溯的结论落库）
- 新增 `PROPOSAL_SYSTEM_PROMPT`，独立于 DECISION_SYSTEM_PROMPT（提示词与 schema 一一对应的惯例保持）；约束包括：只能依据 Evidence、不许猜测、不许因为「同类项目都这么写」就断定本项目用了某项技术、README 与代码冲突时以代码为准、learning_points 必须来自项目实际做法
- Proposal 阶段复用 `build_context(state)`：它渲染的就是 Evidence（metadata 已经在 evidence[0] 里），不重复传 metadata，也不把整个 State 序列化给 LLM
- 失败出口（设计文档第十节，不静默返回假 Proposal）：没有 Evidence / LLM 输出过不了校验 / 引用编号越界 → `status="failed"` + `error`，proposal 置回 None；`LLMNotConfiguredError` 与网络错仍直接抛
- 成功后 `status="analyzing"`（提案是分析阶段的产物）

## tests
- 新增 tests/test_generate_proposal.py（12）：正常生成、title 来自代码（并钉住 ProposalDraft 没有 title 字段）、成品能过 KnowledgeProposal 校验、evidence 正文来自 state、生成阶段不调 Tool（monkeypatch call_tool）、编号越界/输出不合法/无 Evidence 的失败出口、不改传入 state、无 LLM 报错、run() 端到端含 proposal、run() 把 Tool 产出的 evidence 一并带进提案阶段
- 受 run() 三段式影响的现有测试改调 initialize_state()（它们本就在测采集那一步）：test_knowledge_agent（2）、test_agent_decision_llm（6）、test_execute_tool_call（8）、test_investigate（7）、test_investigation_strategy（6）
- 全量 56 passed
- 仍未验证：FakeLLM 的草稿是脚本写死的，所以「LLM 能否从 Evidence 归纳出可靠的提案」没有被验证 —— 需要真实 LLM 客户端

## [1.0.6] - 2026-09-10

## AgentDecision schema
- 新增 schemas/decision.py：AgentDecision（action / tool_name / tool_arguments），ActionType 用 Literal 严格约束为 tool_call / finish，extra="forbid"
- schemas/__init__.py 新增导出 AgentDecision / ActionType
- 暂时**没有**加跨字段校验：action="tool_call" 但 tool_name=None 仍能通过 schema，这个洞目前由 KnowledgeAgent.execute() 兜住

## LLM 决策层（State → LLM → AgentDecision）
- 新增 llm/client.py：LLMClient Protocol（只暴露 complete(system, user, response_model) 一种能力，结构化输出是唯一入口）+ LLMNotConfiguredError。项目原本没有任何 LLM 客户端 / SDK / 配置层，这里定义的是协议而不是实现，真实实现（Anthropic / OpenAI / 本地模型）待补
- 新增 llm/fake.py：FakeLLM，按脚本返回预设决策，不联网、不引入额外依赖；返回值仍走 response_model 校验，所以「LLM 必须结构化输出」这条约束在测试里真实生效
- 新增 agents/prompts.py：DECISION_SYSTEM_PROMPT，工具清单由 tools.TOOL_DESCRIPTIONS 生成，不重抄一遍
- 新增 graph/context.py：build_context(state)，把 state.evidence 渲染成 Context；单条 Evidence 上限 2000 字符、整体上限 8000 字符，截断时显式告知模型（否则模型会把「没看到」当成「不存在」）
- agents/knowledge_agent.py：KnowledgeAgent 新增构造参数 llm=None（不传仍可采集，只有决策时报错）；新增 build_context(state) / decide(state) → AgentDecision
- tools/__init__.py 由空文件改为登记 TOOL_DESCRIPTIONS（对 LLM 可见的工具清单）
- graph/__init__.py 新增导出 build_context

## Tool 执行层（AgentDecision → Tool → Evidence → State）
- 新增 tools/registry.py：ALLOWED_TOOLS（可被执行的工具名单）+ call_tool() + UnsupportedToolError。工具可见（TOOL_DESCRIPTIONS）与可执行（ALLOWED_TOOLS）是两个清单，分开维护
- call_tool 的 owner / repo 一律以当前 State 为准，忽略 LLM 在 tool_arguments 里写的值；多传 / 少传参数都会带 tool_name 与原参数报错
- 新增 schemas/structure.py：ProjectStructure（paths / truncated）
- 新增 tools/get_project_structure.py：返回固定模拟目录结构，不访问 GitHub API（原为空文件）
- graph/evidence.py 新增 structure_to_evidence()（location 用 "." 表示整个仓库）
- schemas/evidence.py：EvidenceType 新增 "structure"
- agents/knowledge_agent.py：新增 execute(state, decision) → KnowledgeProcessState 与 NotAToolCallError；只执行一步，不回头再问 LLM
- tools/__init__.py 增补 re-export ALLOWED_TOOLS / UnsupportedToolError / call_tool
## Tool Calling Loop（investigate）
- agents/knowledge_agent.py 新增 investigate(state)：把 decide() / execute() 串成循环 —— decide 返回 finish 就结束，返回 tool_call 就 execute 后回到 decide
- 分工刻意保持：decide() 只决策一次、execute() 只执行一次，循环只存在于 investigate() 里
- 停止条件两条：① decide() 返回 finish（正常结束，此后不再执行任何 Tool）；② state.tool_call_count 达到模块级 MAX_TOOL_CALLS = 5（安全上限，兜底）
- 上限在 decide() **之前**检查，所以达到上限时不会多问一次 LLM，不存在「最后一次决策被丢弃」
- 达到上限**不改 status**（仍是 collecting）：上限是安全阀，不代表调查完成。因此调用方目前无法区分「LLM 说够了」和「撞上限了」
- execute() 返回的新 State 直接作为下一轮 decide() 的输入，LLM 因此能看到刚补进来的 Evidence
- 不可变设计沿用：investigate() 不新建 State（那是 run() 的事），也不改传入对象
- Tool 仍统一走 registry.call_tool()，没有绕过 execute() 的旁路
- 暂未实现：KnowledgeProposal 生成、Reflection、Relation、数据库、多 Agent、复杂 Harness、Tool 失败自动恢复、真实 LLM 客户端

## 调查策略提示词
- agents/prompts.py 的 DECISION_SYSTEM_PROMPT 换成「调查策略」版本：明确 KnowledgeProposal 需要覆盖的 5 项信息（解决什么问题 / 核心功能 / 主要技术 / 架构与组件 / 至少一个核心机制如何实现），并给出三步 Tool 选择原则（结构 → search_code 定位 → get_file 读实现）
- 另加两条行为约束：不要为了调用 Tool 而调用 Tool；finish 不等于完全了解项目
- 工具清单仍由 tools.TOOL_DESCRIPTIONS 生成，不重抄

## 两个新 Tool（get_file / search_code）
- 新增 tools/_mock_repo.py：mock 仓库的文件内容，get_file 与 search_code 共用一份；文件清单与 get_project_structure.MOCK_PATHS 对齐，且 search_code 搜到的行在 get_file 里真实存在（mock 数据自洽，有测试钉住）
- 新增 tools/get_file.py：get_file(owner, repo, path) → DocumentContent。路径读不到抛 FileNotFoundError（空内容与「文件不存在」是两回事）；对 "./x"、"/x" 这类写法做归一化再查
- 新增 tools/search_code.py：search_code(owner, repo, query) → SearchResult，大小写不敏感，单次上限 SEARCH_LIMIT = 20
- 新增 schemas/search.py：SearchResult（query / matches / truncated）与 CodeMatch（path / line_number / line）
- schemas/evidence.py：EvidenceType 新增 "search"
- graph/evidence.py 新增 search_to_evidence()（location 用 "search:<关键词>"，空结果记为「（没有匹配到任何内容）」而不是空 content）
- registry.ALLOWED_TOOLS 由 1 个扩到 3 个（get_project_structure / get_file / search_code）；get_project_metadata 与 get_readme 仍不在其中 —— 它们只被 run() 直接调用，LLM 无法通过 execute() 点名
- agents/knowledge_agent.py 新增 EVIDENCE_CONVERTERS（tool_name → 转换器映射），替换原先写死的 structure_to_evidence；一个 Tool 要在执行层可用，需在 ALLOWED_TOOLS 与 EVIDENCE_CONVERTERS 同时登记

## 截断标记修复
- 此前 ProjectStructure / DocumentContent 的 truncated=True 在转成 Evidence 时被丢掉，LLM 会把「没看到」当成「不存在」，进而误判信息已经足够
- graph/evidence.py 的 structure_to_evidence / document_to_evidence 现在会在 content 末尾追加「（内容过长，已截断，以上不是全部）」；search_to_evidence 同样处理

## tests
- 新增 tests/test_decision.py（5）、tests/test_agent_decision_llm.py（6）、tests/test_execute_tool_call.py（8）、tests/test_investigate.py（7）、tests/test_investigation_strategy.py（6），共 44 个用例
- test_investigation_strategy 里原有两个「钉住已知缺口」的测试（断言提示词策略走到第二步会因 get_file / search_code 不可执行而中断），已在执行层补齐后改成成功用例
- 未验证项：FakeLLM 的决策是脚本写死的，所以「LLM 能否根据 Evidence 选出合理的 Tool」**没有被验证** —— 这需要真实 LLM 客户端，当前项目没有
- 运行方式：python -m pytest tests -q（pytest 需装进 .venv）

## [1.0.5] - 2026-09-10

## Knowledge Agent 最小版本
- 新增 agents/knowledge_agent.py：KnowledgeAgent(owner, repo)，run() 固定依次调用 get_project_metadata → get_readme，把两个返回值落成 Evidence 写入 State，返回 KnowledgeProcessState（status="collecting"，每次 run 新建 process_id）
- 新增 graph/evidence.py：Tool 产出 → Evidence → State 的代码层转换（metadata_to_evidence / document_to_evidence / record_evidence），Evidence 全程由代码生成，LLM 不参与
- 暂未实现：LLM、Tool Calling Loop、Harness、Reflection、Relation、数据库

## schemas 更新
- 新增 schemas/project.py：ProjectMetadata（name / description / url / language / stars / topics）
- 新增 schemas/document.py：DocumentContent（path / content / truncated），README 与普通源码文件共用
- schemas/__init__.py 新增导出 ProjectMetadata / DocumentContent

## tools 更新
- 新增 tools/get_project_metadata.py：get_project_metadata(owner, repo) → ProjectMetadata，返回固定模拟数据，暂不访问 GitHub API
- 新增 tools/get_readme.py：get_readme(owner, repo) → DocumentContent，返回固定模拟 README，暂不访问 GitHub API
- tools/get_file.py / get_project_structure.py / search_code.py 已建空文件，尚未实现

## tests
- 新增 tests/：test_get_project_metadata（2）、test_get_readme（1）、test_evidence（7）、test_knowledge_agent（2），共 12 个用例
- 运行方式：python -m pytest tests -q

## [1.0.4] - 2026-09-09


## schemas / graph 结构调整
- KnowledgeProcessState / Source / ProcessStatus 由 schemas/process.py 迁移到 graph/state.py（属于 graph 过程状态，而非 LLM 边界 schema）
- 新增 schemas/evidence.py：Evidence / EvidenceType，作为跨 schema 共享的数据结构
- Feature.evidence / Technology.evidence / Architecture.evidence / ReflectionIssue.evidence 由 list[str] 改为 list[Evidence]

## [1.0.3] - 2026-09-09

## schemas 更新
- 新增 relation.py：RelationProposal（relation_type 用 Literal 严格约束）
- 新增 process.py：Source / Evidence / KnowledgeProcessState / ProcessStatus（evidence_type、status 用 Literal 严格约束）
- KnowledgeProposal.title 新增 max_length=200
- Technology.category 改为 Literal 固定枚举（framework / language / database / infrastructure / library / model / other）
- Architecture.pattern 改为允许为空
- ReflectionIssue.type 改为 Literal 固定枚举（factual_error / unsupported_claim / missing_evidence / low_quality / contradiction）
- ReflectionIssue.evidence 由 str 改为 list[str]

## [1.0.2] - 2026-09-09

## schemas 更新
- core_features 属性更新：每项由字符串改为 { description, evidence[] }，数量仍限 1~8
- Technology.evidence 由 str|None 改为 list[str]（默认空列表）
- Architecture 新增 evidence[] 字段

## [1.0.1] - 2026-09-08

## 模块职责
- agents 负责让LLM 做理解、判断、决策。
- tools 负责给Agent 提供能力
- graph 负责谁什么时候执行、以及下一步去哪
- schemas 是LLM世界和传统后端世界之间的边界。
- services 放真正的业务规则
- retrieval 方便换 embedding 模型

