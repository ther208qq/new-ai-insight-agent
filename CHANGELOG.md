# new-ai-insight-agent 版本记录

## [1.0.1] - 2026-09-08

## 模块职责
- agents 负责让LLM 做理解、判断、决策。
- tools 负责给Agent 提供能力
- graph 负责谁什么时候执行、以及下一步去哪
- schemas 是LLM世界和传统后端世界之间的边界。
- services 放真正的业务规则
- retrieval 方便换 embedding 模型

