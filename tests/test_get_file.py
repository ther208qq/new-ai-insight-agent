"""get_file 的测试。

**全部离线**：把 urlopen 换成返回预置 JSON 的假函数，不打 GitHub、不消耗限流
额度。覆盖的是我们自己写的逻辑：URL → owner/repo、path 的拼法、Base64 解码、
以及各种失败翻译成的异常。
"""

import base64
import email.message
import io
import json
import urllib.error
import urllib.request

import pytest

import app.tools.get_file as get_file_module
from app.config import GitHubSettings
from app.tools._github import (
    GitHubAPIError,
    GitHubRateLimitError,
    InvalidRepositoryURLError,
    RepositoryNotFoundError,
)
from app.tools.get_file import get_file
from app.tools.registry import call_tool

_CONTENT = "from demo_project.agent import Agent\n"


def _file_json(**overrides):
    payload = {
        "type": "file",
        "encoding": "base64",
        "path": "app/agents/knowledge_agent.py",
        "size": len(_CONTENT.encode("utf-8")),
        # GitHub 真的每 60 个字符插一个换行，这里照抄
        "content": base64.b64encode(_CONTENT.encode("utf-8")).decode("ascii"),
    }
    return {**payload, **overrides}


def _http_error(code, **headers):
    message = email.message.Message()
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    return urllib.error.HTTPError(
        "https://api.github.com/repos/o/r", code, "err", message, None
    )


def _patch(monkeypatch, outcome, token: str | None = None):
    """把 urlopen 换掉，并让 Tool 拿到指定的 token（不碰环境变量）。"""
    calls = []

    def _open(request, timeout=None):
        calls.append(request)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(json.dumps(outcome).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    monkeypatch.setattr(
        get_file_module,
        "load_github_settings",
        lambda: GitHubSettings(token=token),
    )
    return calls


def test_请求打到_contents_端点并带_owner_repo(monkeypatch):
    calls = _patch(monkeypatch, _file_json())

    get_file("https://github.com/o/r", "app/agents/knowledge_agent.py")

    assert calls[0].full_url == (
        "https://api.github.com/repos/o/r/contents/app/agents/knowledge_agent.py"
    )


def test_多级路径里的斜杠不能被转义(monkeypatch):
    calls = _patch(monkeypatch, _file_json(path="a/b/c.py"))

    get_file("https://github.com/o/r", "a/b/c.py")

    # 转义成 %2F 的话请求会打到别的端点上
    assert "%2F" not in calls[0].full_url
    assert calls[0].full_url.endswith("/contents/a/b/c.py")


def test_base64_被解码成_utf8_文本(monkeypatch):
    _patch(monkeypatch, _file_json())

    document = get_file("https://github.com/o/r", "app/agents/knowledge_agent.py")

    assert document.content == _CONTENT
    assert document.path == "app/agents/knowledge_agent.py"
    # 内容没被截断过，所以这个标记必须如实是 False
    assert document.truncated is False


def test_返回的是_schema_不是_GitHub_的原始_JSON(monkeypatch):
    _patch(monkeypatch, _file_json())

    document = get_file("https://github.com/o/r", "app/agents/knowledge_agent.py")

    assert set(document.model_dump()) == {"path", "content", "truncated"}
    assert "sha" not in document.model_dump_json()
    assert "base64" not in document.model_dump_json()


def test_用_GitHub_回的规范路径而不是入参(monkeypatch):
    _patch(monkeypatch, _file_json(path="app/agents/knowledge_agent.py"))

    # LLM 写 "./" 前缀也能读到，但记进 Evidence 的 location 应该是规范路径
    document = get_file("https://github.com/o/r", "./app/agents/knowledge_agent.py")

    assert document.path == "app/agents/knowledge_agent.py"


def test_404_翻译成_RepositoryNotFoundError_并带上路径(monkeypatch):
    _patch(monkeypatch, _http_error(404))

    with pytest.raises(RepositoryNotFoundError) as excinfo:
        get_file("https://github.com/o/r", "nope.py")

    # 仓库不存在和路径写错都是 404，消息里两个都要提
    assert "nope.py" in str(excinfo.value)
    assert "404" in str(excinfo.value)


def test_限流仍是_GitHubRateLimitError_没被打散(monkeypatch):
    _patch(monkeypatch, _http_error(403, X_RateLimit_Remaining="0"))

    with pytest.raises(GitHubRateLimitError):
        get_file("https://github.com/o/r", "a.py")


def test_非法地址不发请求(monkeypatch):
    calls = _patch(monkeypatch, _file_json())

    for url in ["not a repo", "", None]:
        with pytest.raises(InvalidRepositoryURLError):
            get_file(url, "a.py")

    assert calls == []


def test_目录返回数组时不当成文件(monkeypatch):
    # 目录时 GitHub 回的是数组，不是对象
    _patch(monkeypatch, [{"name": "a.py", "type": "file"}])

    with pytest.raises(GitHubAPIError):
        get_file("https://github.com/o/r", "app/agents")


def test_符号链接不当成文件内容(monkeypatch):
    _patch(monkeypatch, _file_json(type="symlink"))

    with pytest.raises(GitHubAPIError, match="不是普通文件"):
        get_file("https://github.com/o/r", "link.py")


def test_超_1MB_的文件不返回空内容(monkeypatch):
    # >1MB 时 GitHub 只给元数据：encoding="none"、content 为空
    _patch(monkeypatch, _file_json(encoding="none", content="", size=2_000_000))

    # 解出空字符串等于给了一个假文件，必须报错
    with pytest.raises(GitHubAPIError, match="正文没拿到"):
        get_file("https://github.com/o/r", "huge.json")


def test_解不出文本时明确报错(monkeypatch):
    # 合法 Base64，但解出来不是 UTF-8（二进制文件）
    binary = base64.b64encode(b"\xff\xfe\x00\x00binary").decode("ascii")
    _patch(monkeypatch, _file_json(content=binary))

    with pytest.raises(GitHubAPIError, match="解不出文本"):
        get_file("https://github.com/o/r", "a.bin")


def test_带_token_时用_Bearer(monkeypatch):
    calls = _patch(monkeypatch, _file_json(), token="secret-token")

    document = get_file("https://github.com/o/r", "a.py")

    assert calls[0].get_header("Authorization") == "Bearer secret-token"
    # token 只进 header，不进 Tool 产出
    assert "secret-token" not in document.model_dump_json()


def test_不带_token_时不发_Authorization(monkeypatch):
    calls = _patch(monkeypatch, _file_json(), token=None)

    get_file("https://github.com/o/r", "a.py")

    assert calls[0].get_header("Authorization") is None


def test_registry_能直接调起_get_file(monkeypatch):
    """registry 只注入 url，path 由 LLM 给 —— 不需要为 get_file 改 registry。"""
    calls = _patch(monkeypatch, _file_json(path="app/main.py"))

    document = call_tool("get_file", {"path": "app/main.py"}, owner="o", repo="r")

    assert calls[0].full_url.endswith("/repos/o/r/contents/app/main.py")
    assert document.content == _CONTENT


def test_registry_覆盖_LLM_写的_url(monkeypatch):
    calls = _patch(monkeypatch, _file_json(path="app/main.py"))

    call_tool(
        "get_file",
        {"path": "app/main.py", "url": "https://github.com/别人/别的仓库"},
        owner="o",
        repo="r",
    )

    # 用的是 State 里的仓库，不是 LLM 写的
    assert calls[0].full_url.startswith("https://api.github.com/repos/o/r/")
