"""LLM 边界 (LLMClient)。

Agent 要用 LLM 做理解 / 判断 / 决策，但不该关心背后是哪家模型、怎么鉴权。
所以这里只声明一种能力：给一段 system + user 文本，按 response_model
的结构返回一个对象 —— 结构化输出是唯一入口，LLM 的自由文本进不来。

项目里原本没有任何 LLM 客户端，这里定义的是「协议」而不是具体实现：
真实实现（Anthropic / OpenAI / 本地模型）之后再补，测试和未配置 API key
的场景用 app.llm.FakeLLM。这样上层代码只依赖 LLMClient，换模型不动 Agent。
"""

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


class LLMNotConfiguredError(RuntimeError):
    """没有配置 LLM client 就被要求做决策时抛出。"""


@runtime_checkable
class LLMClient(Protocol):
    """LLM 客户端协议：只暴露「结构化输出」这一种调用方式。"""

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_model: type[TModel],
    ) -> TModel:
        """让 LLM 按 response_model 的结构返回结果。

        返回值必须已经过 response_model 校验：调用方拿到的要么是一个合法对象，
        要么是一个异常，不存在「结构不对但能跑下去」的中间态。
        """
        ...
