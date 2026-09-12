"""get_project_metadata 的测试。

**全部离线**：把 urlopen 换成返回预置 JSON 的假函数，不打 GitHub、不消耗限流
额度。用真地址跑一遍是手工验证的事 —— 进了套件就会因为别人改了自己的仓库而变红。

只测这个 Tool 自己写的逻辑：URL → 请求地址、GitHub 的字段 → ProjectMetadata、
必要字段缺失时报错。请求怎么发、状态码怎么翻译，是 _github 的事（几个 Tool 共用
那条路径），这里不重复测。
"""

import email.message
import io
import json
import urllib.error
import urllib.request

import pytest

import app.tools.get_project_metadata as get_project_metadata_module
from app.config import GitHubSettings
from app.tools._github import (
    GitHubAPIError,
    InvalidRepositoryURLError,
    RepositoryNotFoundError,
)
from app.tools.get_project_metadata import get_project_metadata

# 照 GitHub /repos/{owner}/{repo} 的真实形状，只留本项目用得上的字段
_REPO_JSON = {
    "name": "demo-project",
    "description": "一个用于演示 Knowledge Agent 的示例仓库。",
    "html_url": "https://github.com/o/r",
    "language": "Python",
    "stargazers_count": 128,
    "topics": ["agent", "llm"],
}


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
        get_project_metadata_module,
        "load_github_settings",
        lambda: GitHubSettings(token=token),
    )
    return calls


def _http_error(code, **headers):
    message = email.message.Message()
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    return urllib.error.HTTPError(
        "https://api.github.com/repos/o/r", code, "err", message, None
    )


def test_请求打到_repos_端点并带_owner_repo(monkeypatch):
    calls = _patch(monkeypatch, _REPO_JSON)

    get_project_metadata("https://github.com/o/r")

    assert calls[0].full_url == "https://api.github.com/repos/o/r"


def test_裸的_owner_repo_也能用(monkeypatch):
    calls = _patch(monkeypatch, _REPO_JSON)

    get_project_metadata("o/r")

    assert calls[0].full_url == "https://api.github.com/repos/o/r"


def test_正常获取项目元信息(monkeypatch):
    _patch(monkeypatch, _REPO_JSON)

    metadata = get_project_metadata("https://github.com/o/r")

    assert metadata.name == "demo-project"
    assert metadata.description == "一个用于演示 Knowledge Agent 的示例仓库。"
    assert metadata.url == "https://github.com/o/r"
    assert metadata.language == "Python"
    assert metadata.stars == 128
    assert metadata.topics == ["agent", "llm"]


def test_每个字段映射的是_GitHub_的哪个键(monkeypatch):
    _patch(
        monkeypatch,
        {
            # name ← name（不是 full_name）、stars ← stargazers_count。
            # 键写错时下面每一条都会挂，所以这几个都挑成互不相同的值。
            "name": "r",
            "full_name": "o/r",
            "description": "d",
            "html_url": "https://github.com/o/r",
            "homepage": "https://example.com",
            "language": "Python",
            "stargazers_count": 7,
            "forks_count": 999,
            "topics": ["t"],
        },
    )

    metadata = get_project_metadata("https://github.com/o/r")

    assert metadata.name == "r"
    assert metadata.stars == 7
    assert metadata.language == "Python"
    assert metadata.topics == ["t"]


def test_只保留_schema_里的字段(monkeypatch):
    _patch(monkeypatch, {**_REPO_JSON, "forks_count": 999, "license": {"spdx_id": "MIT"}})

    metadata = get_project_metadata("https://github.com/o/r")

    # GitHub 的原始 JSON 不外泄：schema 里没有的字段一个都不带出来
    assert set(metadata.model_dump()) == {
        "name",
        "description",
        "url",
        "language",
        "stars",
        "topics",
    }


def test_仓库没写简介时落成空串(monkeypatch):
    # description 为 null 是常态：仓库没写简介
    _patch(monkeypatch, {**_REPO_JSON, "description": None})

    assert get_project_metadata("https://github.com/o/r").description == ""


def test_判断不出主要语言时为_None(monkeypatch):
    _patch(monkeypatch, {**_REPO_JSON, "language": None})

    # schema 里 None 的含义就是「判断不出来」，不能填成空串
    assert get_project_metadata("https://github.com/o/r").language is None


def test_没有_topics_时为空列表(monkeypatch):
    _patch(monkeypatch, {k: v for k, v in _REPO_JSON.items() if k != "topics"})

    assert get_project_metadata("https://github.com/o/r").topics == []


def test_缺_name_或_stars_时明确报错(monkeypatch):
    for missing in ["name", "stargazers_count"]:
        _patch(monkeypatch, {k: v for k, v in _REPO_JSON.items() if k != missing})

        # 填个默认值就是报假事实（stars 落成 0 = 没人 star），必须报错
        with pytest.raises(GitHubAPIError, match="name / stargazers_count"):
            get_project_metadata("https://github.com/o/r")


def test_地址解析失败时抛_InvalidRepositoryURLError_且不发请求(monkeypatch):
    calls = _patch(monkeypatch, _REPO_JSON)

    for url in ["https://github.com/o/r/tree/main", "not a repo", "", None]:
        with pytest.raises(InvalidRepositoryURLError):
            get_project_metadata(url)

    assert calls == []


def test_仓库不存在抛_RepositoryNotFoundError(monkeypatch):
    _patch(monkeypatch, _http_error(404))

    with pytest.raises(RepositoryNotFoundError):
        get_project_metadata("https://github.com/o/r")


def test_api_请求失败抛_GitHubAPIError(monkeypatch):
    _patch(monkeypatch, urllib.error.URLError("网络断了"))

    with pytest.raises(GitHubAPIError):
        get_project_metadata("https://github.com/o/r")


def test_响应不是合法_JSON_时抛_GitHubAPIError(monkeypatch):
    def _open(request, timeout=None):
        return io.BytesIO(b"<html>502 Bad Gateway</html>")

    monkeypatch.setattr(urllib.request, "urlopen", _open)

    with pytest.raises(GitHubAPIError):
        get_project_metadata("https://github.com/o/r")


def test_带_token_时用_Bearer_且不进入产出(monkeypatch):
    calls = _patch(monkeypatch, _REPO_JSON, token="secret-token")

    metadata = get_project_metadata("https://github.com/o/r")

    assert calls[0].get_header("Authorization") == "Bearer secret-token"

    # token 只进 header，不进 Tool 产出
    assert "secret-token" not in metadata.model_dump_json()


def test_不带_token_时不发_Authorization(monkeypatch):
    calls = _patch(monkeypatch, _REPO_JSON, token=None)

    get_project_metadata("https://github.com/o/r")

    # 公开仓库不带 token 也要能读
    assert calls[0].get_header("Authorization") is None
    assert calls[0].get_header("Accept") == "application/vnd.github+json"
