"""get_readme 的测试。

**全部离线**：把 urlopen 换成返回预置 JSON 的假函数，不打 GitHub、不消耗限流
额度。用真地址跑一遍是手工验证的事 —— 进了套件就会因为别人改了自己的仓库而变红。

只测这个 Tool 自己写的逻辑：URL → 请求地址、Base64 → UTF-8、路径取自响应、
各种失败翻译成的异常。请求怎么发、状态码怎么翻译，是 _github 的事，这里不重复测。
"""

import base64
import email.message
import io
import json
import urllib.error
import urllib.request

import pytest

import app.tools.get_readme as get_readme_module
from app.config import GitHubSettings
from app.graph.context import MAX_EVIDENCE_CHARS
from app.schemas.document import DocumentContent
from app.tools._github import (
    GitHubAPIError,
    InvalidRepositoryURLError,
    RepositoryNotFoundError,
)
from app.tools.get_readme import get_readme

_README = "# Demo Project\n\n一个用于演示 Knowledge Agent 的示例仓库。\n"


def _readme_json(**overrides):
    payload = {
        "type": "file",
        "encoding": "base64",
        "name": "README.md",
        "path": "README.md",
        "size": len(_README.encode("utf-8")),
        # GitHub 真的每 60 个字符插一个换行，这里照抄
        "content": base64.b64encode(_README.encode("utf-8")).decode("ascii"),
    }
    return {**payload, **overrides}


def _patch(monkeypatch, outcome, token: str | None = None):
    """把 urlopen 换掉，并让 Tool 拿到指定的 token（不碰环境变量）。

    返回 calls，里面积着每次的 Request，用来断言请求地址和请求头。
    """
    calls = []

    def _open(request, timeout=None):
        calls.append(request)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(json.dumps(outcome).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    monkeypatch.setattr(
        get_readme_module,
        "load_github_settings",
        lambda: GitHubSettings(token=token),
    )
    return calls


def _http_error(code, **headers):
    message = email.message.Message()
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    return urllib.error.HTTPError(
        "https://api.github.com/repos/o/r/readme", code, "err", message, None
    )


def test_请求打到_readme_端点并带_owner_repo(monkeypatch):
    calls = _patch(monkeypatch, _readme_json())

    get_readme("https://github.com/o/r")

    assert calls[0].full_url == "https://api.github.com/repos/o/r/readme"


def test_不在_url_里猜_readme_的文件名(monkeypatch):
    calls = _patch(monkeypatch, _readme_json())

    get_readme("https://github.com/o/r")

    # 拼 README.md 就是在猜；找 README 是 GitHub 的事
    assert "README" not in calls[0].full_url


def test_裸的_owner_repo_也能用(monkeypatch):
    calls = _patch(monkeypatch, _readme_json())

    get_readme("o/r")

    assert calls[0].full_url == "https://api.github.com/repos/o/r/readme"


def test_正常获取_readme(monkeypatch):
    _patch(monkeypatch, _readme_json())

    document = get_readme("https://github.com/o/r")

    assert isinstance(document, DocumentContent)
    assert document.content == _README
    assert document.path == "README.md"
    # 内容没被截断过，所以这个标记必须如实是 False
    assert document.truncated is False


def test_base64_被解码成_utf8_文本(monkeypatch):
    _patch(monkeypatch, _readme_json())

    document = get_readme("https://github.com/o/r")

    # 拿到的必须是正文，不是那串 Base64
    assert document.content.startswith("# Demo Project")
    assert base64.b64encode(_README.encode("utf-8")).decode("ascii") not in document.content


def test_中文_readme_能正确解码(monkeypatch):
    chinese = "# 项目\n\n这是一个中文 README，含标点「」和 emoji 🚀。\n"
    payload = {
        **_readme_json(),
        "size": len(chinese.encode("utf-8")),
        "content": base64.b64encode(chinese.encode("utf-8")).decode("ascii"),
    }
    _patch(monkeypatch, payload)

    assert get_readme("https://github.com/o/r").content == chinese


def test_路径取自_api_返回的_path_而不是猜(monkeypatch):
    # README 不一定叫 README.md、也不一定在根目录
    _patch(monkeypatch, _readme_json(name="README.rst", path="docs/README.rst"))

    assert get_readme("https://github.com/o/r").path == "docs/README.rst"


def test_没有_path_时退回_name(monkeypatch):
    payload = {k: v for k, v in _readme_json().items() if k != "path"}
    _patch(monkeypatch, payload)

    assert get_readme("https://github.com/o/r").path == "README.md"


def test_path_和_name_都没有时明确报错(monkeypatch):
    payload = {k: v for k, v in _readme_json().items() if k not in ("path", "name")}
    _patch(monkeypatch, payload)

    with pytest.raises(GitHubAPIError, match="path / name"):
        get_readme("https://github.com/o/r")


def test_返回的是_schema_不是_GitHub_的原始_JSON(monkeypatch):
    _patch(monkeypatch, {**_readme_json(), "sha": "abc", "html_url": "https://x"})

    document = get_readme("https://github.com/o/r")

    # GitHub 的原始 JSON 不外泄：schema 里没有的字段一个都不带出来
    assert set(document.model_dump()) == {"path", "content", "truncated"}
    assert "sha" not in document.model_dump_json()


def test_超长_readme_不在这里截断(monkeypatch):
    long_readme = "x" * (MAX_EVIDENCE_CHARS * 3)
    payload = {
        **_readme_json(),
        "content": base64.b64encode(long_readme.encode("utf-8")).decode("ascii"),
    }
    _patch(monkeypatch, payload)

    document = get_readme("https://github.com/o/r")

    # 截断是 Context 层的事（MAX_EVIDENCE_CHARS）；Tool 全量取回，
    # 并且如实报告「没被截断」，否则 LLM 会以为看到的就是全文
    assert len(document.content) == MAX_EVIDENCE_CHARS * 3
    assert document.truncated is False


def test_仓库不存在或没有_readme_都抛_RepositoryNotFoundError(monkeypatch):
    _patch(monkeypatch, _http_error(404))

    with pytest.raises(RepositoryNotFoundError) as excinfo:
        get_readme("https://github.com/o/r")

    # 两种情况都是 404，消息里两个都要提；更不能返回一份空 README
    assert "README" in str(excinfo.value)
    assert "404" in str(excinfo.value)


def test_地址解析失败时抛_InvalidRepositoryURLError_且不发请求(monkeypatch):
    calls = _patch(monkeypatch, _readme_json())

    for url in ["https://github.com/o/r/tree/main", "not a repo", "", None]:
        with pytest.raises(InvalidRepositoryURLError):
            get_readme(url)

    assert calls == []


def test_api_请求失败抛_GitHubAPIError(monkeypatch):
    _patch(monkeypatch, urllib.error.URLError("网络断了"))

    with pytest.raises(GitHubAPIError):
        get_readme("https://github.com/o/r")


def test_响应不是合法_JSON_时抛_GitHubAPIError(monkeypatch):
    def _open(request, timeout=None):
        return io.BytesIO(b"<html>502 Bad Gateway</html>")

    monkeypatch.setattr(urllib.request, "urlopen", _open)

    with pytest.raises(GitHubAPIError):
        get_readme("https://github.com/o/r")


def test_超_1MB_的_readme_不返回空内容(monkeypatch):
    # >1MB 时 GitHub 只给元数据：encoding="none"、content 为空
    _patch(monkeypatch, _readme_json(encoding="none", content="", size=2_000_000))

    # 解出空字符串等于给了一份假 README，必须报错
    with pytest.raises(GitHubAPIError, match="正文没拿到"):
        get_readme("https://github.com/o/r")


def test_符号链接不当成_readme_正文(monkeypatch):
    _patch(monkeypatch, _readme_json(type="symlink"))

    with pytest.raises(GitHubAPIError, match="不是普通文件"):
        get_readme("https://github.com/o/r")


def test_base64_不合法时明确报错(monkeypatch):
    _patch(monkeypatch, _readme_json(content="这不是 base64!!!"))

    with pytest.raises(GitHubAPIError, match="解不出文本"):
        get_readme("https://github.com/o/r")


def test_不是_utf8_时明确报错(monkeypatch):
    # 合法 Base64，但解出来不是 UTF-8（二进制文件）
    binary = base64.b64encode(b"\xff\xfe\x00\x00binary").decode("ascii")
    _patch(monkeypatch, _readme_json(content=binary))

    with pytest.raises(GitHubAPIError, match="解不出文本"):
        get_readme("https://github.com/o/r")


def test_带_token_时用_Bearer_且不进入产出(monkeypatch):
    calls = _patch(monkeypatch, _readme_json(), token="secret-token")

    document = get_readme("https://github.com/o/r")

    assert calls[0].get_header("Authorization") == "Bearer secret-token"

    # token 只进 header，不进 Tool 产出
    assert "secret-token" not in document.model_dump_json()


def test_不带_token_时不发_Authorization(monkeypatch):
    calls = _patch(monkeypatch, _readme_json(), token=None)

    get_readme("https://github.com/o/r")

    # 公开仓库不带 token 也要能读
    assert calls[0].get_header("Authorization") is None
    assert calls[0].get_header("Accept") == "application/vnd.github+json"
