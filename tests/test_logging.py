"""日志模块与打点接入的测试。

抓日志用**公开 API**：`configure_logging(stream=io.StringIO())`，读完 `getvalue()`
即可。刻意不用 pytest 的 `caplog` —— 它抓的是 root，而本项目的日志挂在 `ai_insight`
上（靠 propagate 才被 caplog 看见，多一个隐含前提），而且 `caplog.set_level` 会改
logger 级别，恰好和下面「幂等」「默认级别」这两组断言打架。

前半部分测**装配关系**（handler 装了几次、级别是哪一档），后半部分测**接入点**
（关键信息有没有真的落进日志）。每条只断言「关键信息出现」，不逐字比对整行 ——
那是格式，格式改了不该让一堆测试变红。

**不测 `load_log_settings`**：要控制它就得动环境变量，而它内部调 `load_dotenv`，
那个函数是直接往 `os.environ` 里写值的（不是通过 monkeypatch），一旦测就会把值
留在这个测试进程里，污染后续所有测试 —— 正好破坏本仓库「测试不碰 os.environ」的
性质。既有先例一致：`load_llm_settings` 至今也没有测试。
"""

import io
import logging
from types import SimpleNamespace

import httpx2
import pytest
from openai import BadRequestError
from pydantic import ValidationError

from app.agents.knowledge_agent import MAX_TOOL_CALLS, KnowledgeAgent
from app.agents.reflection import ReflectionReviewer
from app.config import DEFAULT_LOG_LEVEL, LLMSettings, LogSettings
from app.graph.context import MAX_EVIDENCE_CHARS, build_context
from app.graph.state import KnowledgeProcessState, Source
from app.llm import FakeLLM
from app.llm.openai_compatible import OpenAIClient
from app.logging import LOGGER_ROOT, configure_logging, get_logger
from app.schemas.decision import AgentDecision
from app.schemas.evidence import Evidence
from app.schemas.knowledge import (
    Architecture,
    Feature,
    KnowledgeProposal,
    Technology,
)
from app.tools.registry import UnsupportedToolError, call_tool

_OWNER = "example"
_REPO = "demo-project"

_TOOL_CALL = {
    "action": "tool_call",
    "tool_name": "get_project_structure",
    "tool_arguments": {},
}
_FINISH = {"action": "finish"}


def _capture(*, level: str = "INFO") -> io.StringIO:
    """把本项目这棵树的日志导进一个内存 stream 并返回它。

    用 configure_logging(level=...) 而不是 monkeypatch 环境变量 —— 那正是
    「configure_logging 自己不读 env」要换来的东西：测试里给一个 level 就是全部。
    """
    stream = io.StringIO()
    configure_logging(level=level, stream=stream)
    return stream


def _root() -> logging.Logger:
    return logging.getLogger(LOGGER_ROOT)


def _agent(llm=None) -> KnowledgeAgent:
    return KnowledgeAgent(owner=_OWNER, repo=_REPO, llm=llm)


def _proposal() -> KnowledgeProposal:
    return KnowledgeProposal(
        title=f"{_OWNER}/{_REPO}",
        summary="一个用来演示 Knowledge Agent 的示例仓库。",
        problem="验证 Evidence 能否被归纳成可落库的知识。",
        core_features=[Feature(description="固定采集 metadata 与 README")],
        technologies=[Technology(name="Python", category="language")],
        architecture=Architecture(
            pattern="",
            components=["KnowledgeAgent"],
            workflow="采集 → 调查 → 生成提案",
        ),
        learning_points=["Evidence 由代码生成，不交给 LLM"],
    )


def _reflection_evidence() -> list[Evidence]:
    """编号 [1] metadata、[2] readme —— 与 context.py 的编号规则一致。"""
    return [
        Evidence(
            source="metadata",
            location=f"https://github.com/{_OWNER}/{_REPO}",
            content='{"name": "demo-project"}',
            evidence_type="metadata",
        ),
        Evidence(
            source="readme",
            location="README.md",
            content="# Demo Project",
            evidence_type="readme",
        ),
    ]


def _failing_draft() -> dict:
    return {
        "passed": False,
        "issues": [
            {
                "field": "technologies",
                "type": "unsupported_claim",
                "description": "提案称使用 Redis，但 Evidence 里没有任何 Redis 相关内容。",
                "evidence_refs": [],
            }
        ],
        "summary": "有一处断言找不到依据。",
    }


def _state_with(evidence: list[Evidence]) -> KnowledgeProcessState:
    return KnowledgeProcessState(
        process_id="test-process",
        source=Source(url=f"https://github.com/{_OWNER}/{_REPO}", type="github"),
        evidence=evidence,
        status="collecting",
    )


def _wide_evidence(count: int, *, chars: int) -> list[Evidence]:
    """造几条超长的 Evidence，用来触发 context.py 的两层截断。"""
    return [
        Evidence(
            source="readme",
            location=f"README.md#{index}",
            content="一" * chars,
            evidence_type="readme",
        )
        for index in range(1, count + 1)
    ]


# --- 装配：handler 装几次、级别是哪一档 -------------------------------------


def test_configure_会装上自有_handler_并设置级别():
    stream = _capture(level="INFO")

    assert _root().level == logging.INFO
    # handler 挂在 ai_insight 这一层，且只有我们自己这一个
    assert len(_root().handlers) == 1
    assert _root().handlers[0].stream is stream
    # 级别必须设在 logger 上，不能只设在 handler 上：级别检查发生在记录进入
    # 任何 handler 之前，只设 handler 的话 INFO 会被提前丢掉。
    assert _root().propagate is True


def test_重复_configure_不会叠加_handler():
    first = _capture()
    _capture()
    third = _capture()

    handlers = _root().handlers
    assert len(handlers) == 1
    # 留下的是最后一次装的那个，前两次的已被摘掉
    assert handlers[0].stream is third
    # 摘旧的 handler 时顺手 close() 了它，但 StreamHandler.close() 不关底下的
    # stream —— 所以先前那个 StringIO 仍然可读，测试不会莫名其妙拿到空字符串。
    assert first.closed is False


def test_configure_不碰别人的_handler():
    logger = _root()
    foreign = logging.NullHandler()
    logger.addHandler(foreign)

    try:
        _capture()
        # 认准「自己装的」而不是清空 handlers —— 清空会把 pytest / 宿主程序
        # 挂上来的 handler 一起干掉。
        assert foreign in logger.handlers
        assert len(logger.handlers) == 2
    finally:
        logger.removeHandler(foreign)


def test_默认级别是常量_不读环境变量(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")

    configure_logging(stream=io.StringIO())

    # 环境变量里写着 CRITICAL，但 configure_logging 不看 env —— 读 env 是
    # load_log_settings 的事，由调用方显式传进来（见 main.py）。
    assert _root().level == getattr(logging, DEFAULT_LOG_LEVEL)
    assert DEFAULT_LOG_LEVEL == "INFO"


def test_CRITICAL_就是静音():
    stream = _capture(level="CRITICAL")

    logger = get_logger("test")
    logger.info("不该出现")
    logger.warning("也不该出现")

    # 本项目不打 CRITICAL，所以这一档等于关掉 —— 比再加一个 enabled 开关少一个概念。
    assert stream.getvalue() == ""


def test_级别名不区分大小写():
    configure_logging(level="debug", stream=io.StringIO())

    assert _root().level == logging.DEBUG
    # .env 里写小写是常态，而 logging.Logger.setLevel 只认大写精确匹配
    assert LogSettings(level="debug").level == "DEBUG"
    assert LogSettings(level=" Info ").level == "INFO"


def test_未知级别会被拒绝():
    with pytest.raises(ValueError, match="未知日志级别"):
        configure_logging(level="verbose", stream=io.StringIO())

    with pytest.raises(ValidationError):
        LogSettings(level="VERBOSE")


def test_get_logger_挂在_ai_insight_下_且未配置时无副作用():
    logger = get_logger("agent.knowledge")

    assert logger.name == "ai_insight.agent.knowledge"
    # handler 只挂在树根上，子 logger 一个都不带 —— 它们靠 propagate 把记录送上去。
    assert logger.handlers == []


# --- 接入点：关键信息有没有真的落进日志 -------------------------------------


def test_call_tool_会记下_tool_名与仓库():
    stream = _capture()

    call_tool("get_project_structure", {}, owner=_OWNER, repo=_REPO)

    text = stream.getvalue()
    assert "get_project_structure" in text
    assert f"{_OWNER}/{_REPO}" in text


def test_指名不存在的_tool_会先记一条_warning():
    stream = _capture()

    with pytest.raises(UnsupportedToolError, match="不支持的 Tool"):
        call_tool("no_such_tool", {}, owner=_OWNER, repo=_REPO)

    text = stream.getvalue()
    assert "WARNING" in text
    assert "no_such_tool" in text


def test_每轮决策都会记一条_且_finish_被记下():
    stream = _capture()
    agent = _agent(FakeLLM(_TOOL_CALL, _FINISH))

    agent.investigate(agent.initialize_state())

    text = stream.getvalue()
    assert "决策 #1" in text
    assert "决策 #2" in text
    assert "finish" in text
    assert "共调用 Tool 1 次" in text


def test_撞上上限会记一条_warning():
    stream = _capture()
    agent = _agent(FakeLLM(*([_TOOL_CALL] * (MAX_TOOL_CALLS + 3))))

    result = agent.investigate(agent.initialize_state())

    text = stream.getvalue()
    # 撞上限与「LLM 说够了」在 State 上长得一模一样（都是 collecting），
    # 这条 WARNING 是区分二者的唯一痕迹。
    assert "WARNING" in text
    assert f"上限 {MAX_TOOL_CALLS} 次" in text
    assert result.tool_call_count == MAX_TOOL_CALLS
    assert result.status == "collecting"


def test_反思未通过会记一条_warning_并列出_issue_类型():
    stream = _capture()
    reviewer = ReflectionReviewer(FakeLLM(_failing_draft()))

    result = reviewer.run(_proposal(), _reflection_evidence())

    assert result.passed is False
    text = stream.getvalue()
    assert "WARNING" in text
    assert "unsupported_claim" in text


def test_反思通过会记一条_info():
    stream = _capture()
    draft = {"passed": True, "issues": [], "summary": "站得住。"}
    reviewer = ReflectionReviewer(FakeLLM(draft))

    reviewer.run(_proposal(), _reflection_evidence())

    text = stream.getvalue()
    assert "INFO" in text
    assert "反思通过" in text


def test_单条_evidence_被截断只记_debug():
    # 单条超长，但整段并不过长 —— 只该触发单条截断
    state = _state_with(_wide_evidence(1, chars=MAX_EVIDENCE_CHARS * 2))

    stream = _capture(level="DEBUG")
    build_context(state)
    text = stream.getvalue()
    assert "被截断" in text
    assert "DEBUG" in text

    # 默认的 INFO 档看不到它：真实 README 几乎必然触发单条截断，放 INFO 会把
    # 轨迹的骨架淹掉。
    stream = _capture(level="INFO")
    build_context(state)
    assert "被截断" not in stream.getvalue()


def test_context_整体超长会记一条_warning():
    # 每条都被截到 2000 字，加起来仍远超整段上限
    state = _state_with(_wide_evidence(5, chars=MAX_EVIDENCE_CHARS * 2))

    stream = _capture(level="INFO")
    build_context(state)

    text = stream.getvalue()
    assert "WARNING" in text
    assert "Context 超长被截断" in text


def test_打点不改变运行结果():
    # 两次跑用的是同一个 State（investigate 不修改传入对象），所以 process_id
    # 一致、Evidence 一致，唯一变量只有日志级别。
    seed = _agent().initialize_state()

    quiet_stream = _capture(level="CRITICAL")
    quiet = _agent(FakeLLM(_TOOL_CALL, _FINISH)).investigate(seed)

    loud_stream = _capture(level="DEBUG")
    loud = _agent(FakeLLM(_TOOL_CALL, _FINISH)).investigate(seed)

    assert quiet_stream.getvalue() == ""
    assert loud_stream.getvalue() != ""

    assert quiet.evidence == loud.evidence
    assert quiet.tool_call_count == loud.tool_call_count
    assert quiet.status == loud.status
    # 打点不该让任何一步顺手改掉传入的 State
    assert quiet is not seed
    assert loud is not seed


# --- LLM 三档降级 -----------------------------------------------------------


def _degrading_client() -> SimpleNamespace:
    """档 1 / 档 2 被「服务端」拒绝、档 3 正常返回的假 OpenAI 客户端。

    降级以前完全不可见，而它正好解释了「为什么模型偶尔吐回需要 _extract_json
    抠的文本」，所以值得单独测一条。

    BadRequestError 需要 httpx2 的 Response —— openai 3.x 的传递依赖是 httpx2
    （不是 httpx）。这里是本文件唯一碰 openai 内部构造的地方。
    """

    def _reject() -> BadRequestError:
        return BadRequestError(
            "Error code: 400 - response_format is not supported",
            response=httpx2.Response(
                400,
                request=httpx2.Request(
                    "POST", "https://example.invalid/v1/chat/completions"
                ),
            ),
            body=None,
        )

    class _Completions:
        def create(self, **kwargs):
            # 档 1 / 档 2 都会带上 response_format，档 3 不带 —— 用这个区分。
            if "response_format" in kwargs:
                raise _reject()
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"action": "finish"}')
                    )
                ]
            )

    return SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))


def test_降级会各记一条_warning_并最终停在_prompt_档():
    stream = _capture(level="INFO")
    client = OpenAIClient(
        LLMSettings(api_key="k", model="m"), client=_degrading_client()
    )

    decision = client.complete(system="s", user="u", response_model=AgentDecision)

    assert decision.action == "finish"
    assert client.mode == "prompt"

    text = stream.getvalue()
    assert text.count("降级") == 2
    assert "json_schema → json_object" in text
    assert "json_object → prompt" in text
