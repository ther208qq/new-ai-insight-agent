# new-ai-insight-agent 版本记录

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

