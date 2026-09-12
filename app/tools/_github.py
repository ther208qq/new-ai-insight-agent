"""GitHub REST API 的共用客户端。

几个 Tool 都从同一个仓库取证，请求方式、认证、失败分类完全一样，所以收在
这一处：各 Tool 只写「取什么」，不重复写「怎么取」。

只对外暴露 get_json / parse_repo / quote 和几个异常。请求头怎么拼、状态码怎么
翻译，是这一层内部的事。

token 不在这里读：由调用方从 app/config.py 取好传进来，免得这一层也依赖 env
（理由见 load_github_settings 的 docstring）。
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from ghrepo import GHRepo

from app.config import GITHUB_TOKEN_ENV_VAR

GITHUB_API_ROOT = "https://api.github.com"
TIMEOUT_SECONDS = 20
# GitHub 要求带 User-Agent，缺了直接 403
_USER_AGENT = "new-ai-insight-agent"


class InvalidRepositoryURLError(ValueError):
    """传入的不是合法的仓库地址（参数错，不是调用失败）。"""


class GitHubAPIError(RuntimeError):
    """调用 GitHub API 失败。"""


class RepositoryNotFoundError(GitHubAPIError):
    """仓库或路径不存在，或者是私有仓库而无权访问。"""


class GitHubRateLimitError(GitHubAPIError):
    """被限流。等一等能好，与「仓库不存在」处置不同，所以分开。"""


def parse_repo(url: str) -> tuple[str, str]:
    """url → (owner, repo)。

    复用 ghrepo，不自己写 URL 解析：它认 `https://github.com/o/r`、`git@github.com:o/r.git`
    和裸的 `o/r`，也认得出子页面地址（`/tree/main` 这类）是非法输入。
    """
    try:
        ref = GHRepo.parse(url)
    except (ValueError, TypeError) as error:
        # TypeError 也接住：url 不是字符串时 ghrepo 抛的是它，但调用方该看到
        # 的是同一件事「地址不合法」。
        raise InvalidRepositoryURLError(f"不是合法的 GitHub 仓库地址：{url!r}") from error

    return ref.owner, ref.name


def quote(value: str) -> str:
    """整段转义。给 owner / repo / 分支名用 —— 它们不该含路径分隔符。"""
    return urllib.parse.quote(value, safe="")


def get_json(
    url: str,
    token: str | None,
    params: dict[str, str] | None = None,
    accept: str | None = None,
) -> dict:
    """发一个 GET 并解析 JSON。所有失败都归一成 GitHubAPIError 的子类。

    ⚠️ 只接受 JSON **对象**：GitHub 有些端点（比如 contents 传了目录）返回的是
    数组，那在这里就当失败抛掉 —— 调用方拿到的一律是 dict，不必自己判类型。

    accept 用来换媒体类型。个别端点要靠它才给额外字段（代码搜索的 text_matches
    就是这样），不传就用默认的 JSON 类型。
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    request = urllib.request.Request(url, headers=_headers(token, accept))

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        # 必须排在 URLError 之前：HTTPError 是它的子类
        raise _http_error(error) from error
    except TimeoutError as error:
        raise GitHubAPIError(f"请求 GitHub API 超时（{TIMEOUT_SECONDS} 秒）：{url}") from error
    except urllib.error.URLError as error:
        raise GitHubAPIError(f"无法连接 GitHub API：{error.reason}") from error
    except json.JSONDecodeError as error:
        raise GitHubAPIError(f"GitHub 返回的不是合法 JSON：{error}") from error
    except UnicodeDecodeError as error:
        # json.load 自己解码响应体，所以字节流不合法时先抛这个，轮不到上面那条
        raise GitHubAPIError(f"GitHub 返回的内容不是合法的 UTF-8：{error}") from error

    if not isinstance(payload, dict):
        # 常见于「把目录当文件读」：contents 端点对目录返回的是条目数组。
        # 说清楚是数组，才看得出该换个路径，而不是以为 GitHub 出错了。
        raise GitHubAPIError(
            f"GitHub 返回的是 {type(payload).__name__} 而不是对象："
            f"这个地址指向的是一组内容（比如目录），不是单个文件。"
        )
    return payload


def _headers(token: str | None, accept: str | None = None) -> dict[str, str]:
    """请求头。token 只在这一处出现，且只进 header。"""
    headers = {
        "Accept": accept or "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        # 不写就用 GitHub 的默认版本，而默认值会变，响应形状可能跟着变
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_error(error: urllib.error.HTTPError) -> GitHubAPIError:
    """HTTP 状态码 → 异常。403 在 GitHub 有两种含义，必须按响应头分开判。"""
    if error.code == 404:
        return RepositoryNotFoundError(
            f"仓库或路径不存在，或者无权访问（GitHub 返回 404）。私有仓库需要设置 "
            f"{GITHUB_TOKEN_ENV_VAR}。"
        )

    if error.code == 401:
        return GitHubAPIError(
            f"{GITHUB_TOKEN_ENV_VAR} 无效或已过期（GitHub 返回 401）。"
        )

    if _is_rate_limited(error):
        return GitHubRateLimitError(
            f"GitHub API 限流（返回 {error.code}）。未认证请求是 60 次/小时，"
            f"设置 {GITHUB_TOKEN_ENV_VAR} 可提到 5000 次/小时。"
        )

    return GitHubAPIError(f"GitHub API 返回 {error.code}：{error.reason}")


def _is_rate_limited(error: urllib.error.HTTPError) -> bool:
    if error.code == 429:
        return True

    # 限流时 Remaining 一定是 "0"。比解析错误文案可靠：文案会变，而且「被限流」
    # 和「没权限」的响应体长得很像。
    remaining = error.headers.get("X-RateLimit-Remaining") if error.headers else None
    return remaining == "0"
