# new-ai-insight-agent 版本记录

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

