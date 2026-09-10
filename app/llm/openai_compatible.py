"""OpenAI 兼容端点的 LLM 实现。

任何说 /chat/completions 这一套的服务都能接：OpenAI、DeepSeek、通义千问、
Moonshot、智谱、vLLM、Ollama…… 换一家只改 .env 里的 base_url / model。

结构化输出（LLMClient.complete 的 response_model）分三档，从强到弱：

1. **json_schema** —— response_format 里给 JSON Schema 且 strict。字段名、类型、
   必填全由服务端保证，模型没有机会返回别的形状。
2. **json_object** —— 服务端只保证「回复是合法 JSON」，schema 靠提示词交代，
   由 pydantic 兜底校验。（DeepSeek 停在这一档：它支持 json_object，但没有
   json_schema。）
3. **纯提示词** —— 连 json_object 都不支持时：schema 只写在提示词里，拿回来
   剥掉可能的代码块 / 前后话，再用 pydantic 校验。

三档的差别只在「谁来保证结构」：档 1 是服务端，档 2 和 3 都是 pydantic。
所以即便停在档 3，调用方拿到的也一定是合法对象或者一个异常 —— 不存在
「结构不对但能跑下去」的中间态，这是 LLMClient 协议的要求。

降级只在「服务端明确说不支持 response_format」时发生（见 _looks_like_unsupported），
其他错误照抛 —— 否则模型名写错之类的问题会被伪装成「降级后仍然失败」，更难查。
每退一档就记住（_mode），后续调用不再白试。
"""

import json
from typing import Any

from openai import BadRequestError, OpenAI
from pydantic import BaseModel

from app.config import LLMSettings
from app.llm.client import TModel

# 服务端拒绝 response_format 时，报错里一般会带上这几个词之一。
_UNSUPPORTED_HINTS = ("response_format", "json_schema", "json mode", "json_object")

# 结构化输出的三档，从强到弱（见模块 docstring）。
_JSON_SCHEMA_MODE = "json_schema"
_JSON_OBJECT_MODE = "json_object"
_PROMPT_MODE = "prompt"

_SCHEMA_PROMPT_TEMPLATE = """

你必须只输出一个 JSON 对象，且必须符合下面的 JSON Schema：

{schema}

不要输出任何解释、前后缀，也不要用 markdown 代码块包裹。
"""


class OpenAIClient:
    """LLMClient 的 OpenAI 兼容实现。

    client 参数只给测试用（塞一个假的进来就不用联网）；不传就按 settings 建真的。
    """

    def __init__(self, settings: LLMSettings, client: OpenAI | None = None) -> None:
        self.settings = settings
        self._client = client or OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout,
        )
        # 当前能用到哪一档。第一次被拒就往下退一档，之后不再白试。
        self._mode = _JSON_SCHEMA_MODE

    @property
    def mode(self) -> str:
        """当前实际走的是哪一档：json_schema / json_object / prompt。"""
        return self._mode

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_model: type[TModel],
    ) -> TModel:
        # 逐档往下试：被拒一档就退一档，然后立刻用新档重试。所以第一次调用
        # 最多发三次请求，之后就一直停在试通的那一档，不再重复试探。
        if self._mode == _JSON_SCHEMA_MODE:
            try:
                return self._complete_with_schema(system, user, response_model)
            except BadRequestError as error:
                if not _looks_like_unsupported(str(error)):
                    raise
                self._mode = _JSON_OBJECT_MODE

        if self._mode == _JSON_OBJECT_MODE:
            try:
                return self._complete_with_json_object(system, user, response_model)
            except BadRequestError as error:
                if not _looks_like_unsupported(str(error)):
                    raise
                self._mode = _PROMPT_MODE

        return self._complete_with_prompt(system, user, response_model)

    def _complete_with_schema(
        self,
        system: str,
        user: str,
        response_model: type[TModel],
    ) -> TModel:
        response = self._client.chat.completions.create(
            model=self.settings.model,
            messages=_messages(system, user),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": _strict_schema(response_model),
                    "strict": True,
                },
            },
            **_sampling(self.settings),
        )

        return response_model.model_validate_json(_message_text(response))

    def _complete_with_json_object(
        self,
        system: str,
        user: str,
        response_model: type[TModel],
    ) -> TModel:
        """档 2：服务端保证回的是合法 JSON，字段对不对仍由 pydantic 判。"""
        return self._complete_with_schema_in_prompt(
            system, user, response_model, response_format={"type": "json_object"}
        )

    def _complete_with_prompt(
        self,
        system: str,
        user: str,
        response_model: type[TModel],
    ) -> TModel:
        """档 3：连 json_object 都没有，那就只靠提示词。"""
        return self._complete_with_schema_in_prompt(
            system, user, response_model, response_format=None
        )

    def _complete_with_schema_in_prompt(
        self,
        system: str,
        user: str,
        response_model: type[TModel],
        *,
        response_format: dict[str, str] | None,
    ) -> TModel:
        """档 2 / 档 3 共用的那条路：schema 写在提示词里，回来自己校验。

        区别只有 response_format 传不传 —— 传了服务端会保证是合法 JSON。
        """
        schema = json.dumps(
            response_model.model_json_schema(), ensure_ascii=False, indent=2
        )
        request: dict[str, Any] = {
            "model": self.settings.model,
            "messages": _messages(
                system + _SCHEMA_PROMPT_TEMPLATE.format(schema=schema), user
            ),
            **_sampling(self.settings),
        }
        if response_format is not None:
            request["response_format"] = response_format

        response = self._client.chat.completions.create(**request)
        return response_model.model_validate_json(_extract_json(_message_text(response)))


def _messages(system: str, user: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _sampling(settings: LLMSettings) -> dict[str, Any]:
    """采样参数。max_tokens 留空就不传 —— 有些服务端由自己决定上限。

    用 max_tokens 而不是 max_completion_tokens：前者是各家兼容端点的最大公约数
    （DeepSeek / 通义 / vLLM / Ollama 都认）。
    """
    params: dict[str, Any] = {"temperature": settings.temperature}
    if settings.max_tokens is not None:
        params["max_tokens"] = settings.max_tokens
    return params


def _message_text(response: Any) -> str:
    """从回复里取正文。取不到就报错，别让下游拿到空字符串去猜。"""
    choices = getattr(response, "choices", None)
    if not choices:
        raise ValueError("LLM 回复里没有 choices")

    content = choices[0].message.content
    if not content:
        raise ValueError("LLM 回复的 content 为空")
    return content


def _strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """把 pydantic 生成的 schema 调成严格模式要求的样子。

    严格模式要求每个 object 的 required 列全所有 properties，且
    additionalProperties 为 false。pydantic 对有默认值的字段不会放进 required
    （AgentDecision.tool_name、DraftFeature.evidence_refs 都是这种），所以这里
    递归补一遍 —— 不补的话服务端会直接 400。
    """
    schema = model.model_json_schema()
    _require_every_property(schema)
    return schema


def _require_every_property(node: Any) -> None:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
            node["additionalProperties"] = False
        for value in node.values():
            _require_every_property(value)
    elif isinstance(node, list):
        for item in node:
            _require_every_property(item)


def _extract_json(text: str) -> str:
    """从模型回复里抠出 JSON 文本。

    降级那条路上模型可能先来一句「好的，这是提案」、或者用 ```json 裹起来，
    两种都得兜住。抠不出来就原样返回，交给 pydantic 去报一条明确的错。
    """
    text = text.strip()

    if text.startswith("```"):
        # 去掉首行的 ``` 或 ```json
        _, _, text = text.partition("\n")
        text = text.rstrip()
        if text.endswith("```"):
            text = text[: -len("```")]
        text = text.strip()

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return text

    return text[start : end + 1]


def _looks_like_unsupported(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _UNSUPPORTED_HINTS)
