"""不访问网络的 LLM 实现 (FakeLLM)。

和 tools/ 里返回固定模拟数据是同一个思路：本地开发、单元测试、没配 API key
时用它跑通链路，不引入任何额外依赖，也不发网络请求。

刻意保留的一点：返回值仍然走 response_model 校验。所以「LLM 必须按
AgentDecision 结构化输出」这条约束在测试里是真的在生效，而不是被 fake 绕过去。
"""

from typing import Any

from pydantic import BaseModel

from app.llm.client import TModel


class FakeLLM:
    """按预设脚本返回结果的 LLM。

    FakeLLM({"action": "finish"})            # 第一次调用返回这个决策
    FakeLLM(decision_a, decision_b)          # 依次返回，模拟多轮决策

    脚本用完后再被调用会直接报错 —— 与其悄悄重复最后一个决策，
    不如让「循环转了多余的一圈」立刻暴露出来。
    """

    def __init__(self, *scripted: BaseModel | dict[str, Any] | str) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, str]] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_model: type[TModel],
    ) -> TModel:
        self.calls.append({"system": system, "user": user})

        if not self._scripted:
            raise AssertionError("FakeLLM 的脚本已用完，但仍被调用了一次")

        item = self._scripted.pop(0)

        if isinstance(item, str):
            # 模拟 LLM 直接吐出一段 JSON 文本
            return response_model.model_validate_json(item)
        if isinstance(item, BaseModel):
            item = item.model_dump()
        return response_model.model_validate(item)
