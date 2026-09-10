# new-ai-insight-agent 版本记录

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

