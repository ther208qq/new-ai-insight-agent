"""search_code 的测试。

**全部离线**：把 urlopen 换成返回预置 JSON 的假函数，不打 GitHub、不消耗那
10 次/分钟的代码搜索额度。覆盖的是我们自己写的逻辑：q 怎么拼、Accept 头、
字节偏移 → 行、去重、截断标记、以及各类失败。

GitHub 那边的行为不归这里管，但**编排方式**要照着真的来：indices 用 UTF-8
字节偏移（见 _match），这是实测出来的接口行为，写错了整个取行逻辑就是错的。
"""

import email.message
import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

import app.tools.search_code as search_code_module
from app.config import GitHubSettings
from app.tools._github import (
    GitHubAPIError,
    InvalidRepositoryURLError,
    RepositoryNotFoundError,
)
from app.tools.registry import call_tool
from app.tools.search_code import SEARCH_LIMIT, EmptyQueryError, search_code

_FRAGMENT = "def call_tool(\n    tool_name: str,\n    tool_arguments: dict[str, Any] | None,\n)"


def _match(fragment: str, text: str) -> dict:
    """造一条 text_match。indices 是 UTF-8 **字节**偏移，照 GitHub 的规则算。"""
    start = fragment.find(text)
    return {
        "fragment": fragment,
        "matches": [{"text": text, "indices": [len(fragment[:start].encode("utf-8")), 0]}],
    }


def _item(path: str, fragment: str, text: str) -> dict:
    return {"path": path, "text_matches": [_match(fragment, text)]}


def _search_json(*items: dict, total_count: int | None = None, incomplete=False) -> dict:
    return {
        "total_count": len(items) if total_count is None else total_count,
        "incomplete_results": incomplete,
        "items": list(items),
    }


def _http_error(code, **headers):
    message = email.message.Message()
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    return urllib.error.HTTPError(
        "https://api.github.com/search/code", code, "err", message, None
    )


def _patch(monkeypatch, outcome, token: str | None = "t"):
    calls = []

    def _open(request, timeout=None):
        calls.append(request)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(json.dumps(outcome).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    monkeypatch.setattr(
        search_code_module,
        "load_github_settings",
        lambda: GitHubSettings(token=token),
    )
    return calls


def _query_of(call) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlparse(call.full_url).query)["q"][0]


def test_请求打到代码搜索端点并按_repo_限定范围(monkeypatch):
    calls = _patch(monkeypatch, _search_json(_item("a.py", _FRAGMENT, "call_tool")))

    search_code("https://github.com/o/r", "call_tool")

    assert calls[0].full_url.startswith("https://api.github.com/search/code?")
    assert _query_of(calls[0]) == "call_tool repo:o/r"


def test_q_是被编码过的不是手拼的(monkeypatch):
    calls = _patch(monkeypatch, _search_json())

    search_code("https://github.com/o/r", "def call_tool")

    # 空格和 : / 都必须转义好，否则 q 会被截断
    assert "q=def+call_tool+repo%3Ao%2Fr" in calls[0].full_url
    # 解析回来还是原样的关键词
    assert _query_of(calls[0]) == "def call_tool repo:o/r"


def test_必须带_text_match_媒体类型(monkeypatch):
    calls = _patch(monkeypatch, _search_json())

    search_code("https://github.com/o/r", "x")

    # 不带它 GitHub 只给文件路径，连那一行是什么都不给
    assert calls[0].get_header("Accept") == "application/vnd.github.text-match+json"


def test_结果转成_path_和匹配所在行(monkeypatch):
    _patch(monkeypatch, _search_json(_item("app/tools/registry.py", _FRAGMENT, "call_tool")))

    result = search_code("https://github.com/o/r", "call_tool")

    assert result.query == "call_tool"
    assert len(result.matches) == 1
    assert result.matches[0].path == "app/tools/registry.py"
    assert result.matches[0].line == "def call_tool("
    # 这个接口不返回行号，所以这里必须是 None 而不是编一个数
    assert result.matches[0].line_number is None


def test_片段里有中文时也能取对行(monkeypatch):
    # 中文是多字节，字节偏移和字符偏移会差开 —— 差开就会取到后面几行
    fragment = '"""工具注册。"""\n\n\nimport inspect\n\n\ndef call_tool(\n    tool_name: str,\n)'
    _patch(monkeypatch, _search_json(_item("registry.py", fragment, "call_tool")))

    result = search_code("https://github.com/o/r", "call_tool")

    assert result.matches[0].line == "def call_tool("


def test_同一个文件里的多段匹配都会返回(monkeypatch):
    item = {
        "path": "a.py",
        "text_matches": [
            _match("call_tool(x)", "call_tool"),
            _match("y = call_tool(z)", "call_tool"),
        ],
    }
    _patch(monkeypatch, _search_json(item))

    result = search_code("https://github.com/o/r", "call_tool")

    assert [m.line for m in result.matches] == ["call_tool(x)", "y = call_tool(z)"]


def test_同一行命中多次只留一条(monkeypatch):
    item = {
        "path": "a.py",
        "text_matches": [
            _match("call_tool(call_tool)", "call_tool"),
            _match("call_tool(call_tool)", "call_tool"),
        ],
    }
    _patch(monkeypatch, _search_json(item))

    result = search_code("https://github.com/o/r", "call_tool")

    assert len(result.matches) == 1


def test_搜不到是正常结果不是异常(monkeypatch):
    _patch(monkeypatch, _search_json())

    result = search_code("https://github.com/o/r", "不存在的东西")

    assert result.matches == []
    assert result.truncated is False


def test_空_query_报错且不发请求(monkeypatch):
    calls = _patch(monkeypatch, _search_json())

    for query in ["", "   "]:
        with pytest.raises(EmptyQueryError):
            search_code("https://github.com/o/r", query)

    # 空结果的意思是「这个词不在仓库里」，空 query 不是那回事，不能混
    assert calls == []


def test_非法地址抛_InvalidRepositoryURLError(monkeypatch):
    calls = _patch(monkeypatch, _search_json())

    with pytest.raises(InvalidRepositoryURLError):
        search_code("not a repo", "x")

    assert calls == []


def test_仓库不存在抛_RepositoryNotFoundError(monkeypatch):
    _patch(monkeypatch, _http_error(404))

    with pytest.raises(RepositoryNotFoundError):
        search_code("https://github.com/o/r", "x")


def test_没配_token_时的_401_能被看懂(monkeypatch):
    # 代码搜索必须认证，匿名调用回的就是 401
    _patch(monkeypatch, _http_error(401))

    with pytest.raises(GitHubAPIError):
        search_code("https://github.com/o/r", "x")


def test_github_自己说不完整时标记截断(monkeypatch):
    _patch(monkeypatch, _search_json(_item("a.py", _FRAGMENT, "call_tool"), incomplete=True))

    assert search_code("https://github.com/o/r", "x").truncated is True


def test_匹配的文件比给我们的多时标记截断(monkeypatch):
    # total_count 是文件数，比 items 多说明 GitHub 只给了前一批
    _patch(monkeypatch, _search_json(_item("a.py", _FRAGMENT, "call_tool"), total_count=99))

    assert search_code("https://github.com/o/r", "x").truncated is True


def test_结果条数按_SEARCH_LIMIT_截断(monkeypatch):
    items = [
        _item(f"f{i}.py", f"x = call_tool_{i}", "call_tool")
        for i in range(SEARCH_LIMIT + 5)
    ]
    _patch(monkeypatch, _search_json(*items, total_count=len(items)))

    result = search_code("https://github.com/o/r", "call_tool")

    assert len(result.matches) == SEARCH_LIMIT
    assert result.truncated is True


def test_缺片段的条目被跳过不炸(monkeypatch):
    items = [
        {"path": "no-matches.py"},
        {"path": "empty.py", "text_matches": []},
        {"path": "no-fragment.py", "text_matches": [{"matches": [{"text": "x", "indices": [0, 1]}]}]},
        _item("ok.py", _FRAGMENT, "call_tool"),
    ]
    _patch(monkeypatch, _search_json(*items))

    result = search_code("https://github.com/o/r", "x")

    assert [m.path for m in result.matches] == ["ok.py"]


def test_返回的是_schema_不是_GitHub_的原始_JSON(monkeypatch):
    _patch(monkeypatch, _search_json(_item("a.py", _FRAGMENT, "call_tool")))

    result = search_code("https://github.com/o/r", "call_tool")

    assert set(result.model_dump()) == {"query", "matches", "truncated"}
    assert set(result.matches[0].model_dump()) == {"path", "line_number", "line"}
    assert "text_matches" not in result.model_dump_json()
    assert "sha" not in result.model_dump_json()


def test_registry_能直接调起_search_code(monkeypatch):
    """registry 只注入 url，query 由 LLM 给 —— 不需要为 search_code 改 registry。"""
    calls = _patch(monkeypatch, _search_json(_item("a.py", _FRAGMENT, "call_tool")))

    result = call_tool("search_code", {"query": "call_tool"}, owner="o", repo="r")

    assert _query_of(calls[0]) == "call_tool repo:o/r"
    assert result.matches[0].line == "def call_tool("
