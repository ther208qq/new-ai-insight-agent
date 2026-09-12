"""get_project_structure 的测试。

**全部离线**：把 urlopen 换成按脚本返回预置 JSON 的假函数，不打 GitHub、不消耗
限流额度。用真地址跑一遍是手工验证的事 —— 进了套件就会因为别人改了自己的仓库
而变红。

只测我们自己写的逻辑：URL → owner/repo、两步请求的次序、tree[] → paths、两种
截断的合并、失败翻译成的异常。GitHub 那边的行为不归这里管。
"""

import email.message
import io
import json
import urllib.error
import urllib.request

import pytest

import app.tools.get_project_structure as get_project_structure_module
from app.config import GitHubSettings
from app.tools._github import (
    GitHubAPIError,
    GitHubRateLimitError,
    InvalidRepositoryURLError,
    RepositoryNotFoundError,
)
from app.tools.get_project_structure import MAX_PATHS, get_project_structure

_REPO_JSON = {"default_branch": "main"}
_TREE_JSON = {
    "tree": [
        {"path": "app", "type": "tree"},
        {"path": "app/main.py", "type": "blob"},
        {"path": "README.md", "type": "blob"},
    ],
    "truncated": False,
}


def _fake_urlopen(*outcomes):
    """按顺序返回预置响应；元素是 Exception 就抛出来。

    返回 (假函数, calls)，calls 里记着每次的 Request，用来断言请求的 URL 和请求头。
    """
    calls = []
    queue = list(outcomes)

    def _open(request, timeout=None):
        calls.append(request)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(json.dumps(outcome).encode("utf-8"))

    return _open, calls


def _http_error(code, **headers):
    message = email.message.Message()
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    return urllib.error.HTTPError(
        "https://api.github.com/repos/o/r", code, "err", message, None
    )


def _patch(monkeypatch, *outcomes):
    fake, calls = _fake_urlopen(*outcomes)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def test_url_先解析出_owner_repo_再按默认分支取树(monkeypatch):
    calls = _patch(monkeypatch, _REPO_JSON, _TREE_JSON)

    get_project_structure("https://github.com/o/r")

    # 第一步问仓库、第二步按 default_branch 取递归树 —— 次序不能反
    assert calls[0].full_url == "https://api.github.com/repos/o/r"
    assert calls[1].full_url.startswith(
        "https://api.github.com/repos/o/r/git/trees/main"
    )


def test_recursive_参数必须带上(monkeypatch):
    calls = _patch(monkeypatch, _REPO_JSON, _TREE_JSON)

    get_project_structure("https://github.com/o/r")

    # 不带 recursive=1 只会返回顶层，结构就不完整了
    assert "recursive=1" in calls[1].full_url


def test_默认分支不是_main_时用仓库自己报的那个(monkeypatch):
    """硬编码 main 的话这条会失败 —— 顺带钉住「不假设默认分支叫 main」。"""
    calls = _patch(monkeypatch, {"default_branch": "master"}, _TREE_JSON)

    get_project_structure("https://github.com/o/r")

    assert "git/trees/master" in calls[1].full_url
    assert "main" not in calls[1].full_url


def test_tree_里的_path_原样进_paths(monkeypatch):
    _patch(monkeypatch, _REPO_JSON, _TREE_JSON)

    structure = get_project_structure("https://github.com/o/r")

    # 只取 path，且不区分目录与文件（schema 明说不在这里判断）：
    # tree 类型的 "app" 不补尾斜杠。
    assert structure.paths == ["app", "app/main.py", "README.md"]
    assert structure.truncated is False


def test_裸的_owner_repo_也能用(monkeypatch):
    _patch(monkeypatch, _REPO_JSON, _TREE_JSON)

    assert get_project_structure("o/r").paths == ["app", "app/main.py", "README.md"]


def test_github_自己截断时_truncated_为真(monkeypatch):
    _patch(monkeypatch, _REPO_JSON, {**_TREE_JSON, "truncated": True})

    assert get_project_structure("https://github.com/o/r").truncated is True


def test_路径超过上限时按_MAX_PATHS_截断并标记(monkeypatch):
    many = {"tree": [{"path": f"f{i}.py", "type": "blob"} for i in range(MAX_PATHS + 50)]}
    _patch(monkeypatch, _REPO_JSON, many)

    structure = get_project_structure("https://github.com/o/r")

    assert len(structure.paths) == MAX_PATHS
    # 截断了就必须说，否则 LLM 会把「没看到」当成「不存在」
    assert structure.truncated is True


def test_仓库不存在抛_RepositoryNotFoundError(monkeypatch):
    _patch(monkeypatch, _http_error(404))

    with pytest.raises(RepositoryNotFoundError):
        get_project_structure("https://github.com/o/r")


def test_限流抛_GitHubRateLimitError(monkeypatch):
    _patch(monkeypatch, _http_error(403, X_RateLimit_Remaining="0"))

    with pytest.raises(GitHubRateLimitError):
        get_project_structure("https://github.com/o/r")


def test_403_但不是限流时不报成限流(monkeypatch):
    """403 也用于「有身份但无权看这个仓库」，等多久都没用，不能混为一谈。"""
    _patch(monkeypatch, _http_error(403, X_RateLimit_Remaining="59"))

    with pytest.raises(GitHubAPIError) as excinfo:
        get_project_structure("https://github.com/o/r")

    assert not isinstance(excinfo.value, GitHubRateLimitError)


def test_非法地址不打网络请求(monkeypatch):
    calls = _patch(monkeypatch)

    with pytest.raises(InvalidRepositoryURLError):
        get_project_structure("https://github.com/o/r/tree/main")

    assert calls == []


def test_各种非法输入都抛_InvalidRepositoryURLError(monkeypatch):
    _patch(monkeypatch)

    for url in ["not a repo", "", None]:
        with pytest.raises(InvalidRepositoryURLError):
            get_project_structure(url)


def _patch_settings(monkeypatch, token: str | None) -> None:
    """指定 Tool 会拿到的 token。

    不动环境变量：load_github_settings 内部会 load_dotenv，setenv/delenv 都可能
    被本机 .env 盖回去，断言就跟着本机配置忽明忽暗。「怎么读出来的」归 config 管。
    """
    monkeypatch.setattr(
        get_project_structure_module,
        "load_github_settings",
        lambda: GitHubSettings(token=token),
    )


def test_不带_token_时不发_Authorization(monkeypatch):
    _patch_settings(monkeypatch, None)
    calls = _patch(monkeypatch, _REPO_JSON, _TREE_JSON)

    get_project_structure("https://github.com/o/r")

    # 公开仓库不带 token 也要能读
    assert calls[0].get_header("Authorization") is None
    assert calls[0].get_header("Accept") == "application/vnd.github+json"


def test_带_token_时用_Bearer(monkeypatch):
    _patch_settings(monkeypatch, "secret-token")
    calls = _patch(monkeypatch, _REPO_JSON, _TREE_JSON)

    get_project_structure("https://github.com/o/r")

    assert calls[0].get_header("Authorization") == "Bearer secret-token"


def test_token_不会进入_Tool_Result(monkeypatch):
    _patch_settings(monkeypatch, "secret-token")
    _patch(monkeypatch, _REPO_JSON, _TREE_JSON)

    structure = get_project_structure("https://github.com/o/r")

    assert "secret-token" not in structure.model_dump_json()
