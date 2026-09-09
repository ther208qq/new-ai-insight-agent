# new-ai-insight-agent 版本记录

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

