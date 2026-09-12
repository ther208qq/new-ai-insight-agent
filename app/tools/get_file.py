"""读取仓库中某个文件内容的 Tool。

走 GitHub REST API：

    GET /repos/{owner}/{repo}/contents/{path}

正文以 Base64 回来，这里解码成 UTF-8 文本再包成 DocumentContent —— GitHub 的
原始 JSON 不往上抛，Tool 的产出必须有稳定的形状。

内容**不在这里截断**：截断是 Context 层的职责（见 graph/context 的
MAX_EVIDENCE_CHARS），Tool 只负责如实取回。唯一要挡的是 GitHub 自己不给正文的
情况（超过 1MB 的文件）。

路径读不到时抛异常（而不是返回空内容）：空内容和「文件不存在」是两回事，
混在一起会让 LLM 以为自己读到了一个空文件。
"""

import base64
import urllib.parse

from app.config import load_github_settings
from app.schemas.document import DocumentContent
from app.tools._github import (
    GITHUB_API_ROOT,
    GitHubAPIError,
    RepositoryNotFoundError,
    get_json,
    parse_repo,
    quote,
)


def get_file(url: str, path: str) -> DocumentContent:
    """返回仓库中 path 所指文件的内容。

    不指定分支（GitHub 的 ref 参数）：和 get_project_structure 一样读默认分支，
    两个 Tool 看到的必须是同一份树，否则结构里列出的文件可能读不到。
    """
    owner, repo = parse_repo(url)
    api_url = (
        f"{GITHUB_API_ROOT}/repos/{quote(owner)}/{quote(repo)}"
        # path 里的 / 是路径分隔符，不能转义成 %2F，否则请求会打到别的端点上
        f"/contents/{urllib.parse.quote(path, safe='/')}"
    )

    # token 只在这里取一次，读 env 是 app/config.py 的事
    token = load_github_settings().token

    try:
        payload = get_json(api_url, token)
    except RepositoryNotFoundError as error:
        # 路径写错和仓库不存在，GitHub 回的都是 404，分不出来 —— 只说「仓库不存在」
        # 会把人引到错的方向。子类原样抛回去，别打散成父类。
        raise RepositoryNotFoundError(
            f"{owner}/{repo} 里读不到 {path!r}（GitHub 返回 404）："
            f"路径写错了，或者仓库本身不存在。"
        ) from error

    return _to_document(payload, path=path)


def _to_document(payload: dict, *, path: str) -> DocumentContent:
    """GitHub 的 contents 响应 → DocumentContent。"""
    if payload.get("type") != "file":
        # 目录会返回数组，那一步在 _get_json 就拦掉了；能走到这里的 type 只有
        # file / symlink / submodule。后两者给的「正文」其实是链接目标，当文件内容
        # 返回等于给了个假文件。
        raise GitHubAPIError(
            f"{path!r} 不是普通文件（type={payload.get('type')!r}）："
            f"可能是符号链接或子模块。"
        )

    raw = payload.get("content")
    if payload.get("encoding") != "base64" or raw is None:
        # 超过 1MB 的文件 GitHub 只给元数据、不给正文。照常往下走会解出一个空
        # 字符串 —— 那是个假文件，比报错更糟。
        raise GitHubAPIError(
            f"{path!r} 的正文没拿到（encoding={payload.get('encoding')!r}，"
            f"size={payload.get('size')} 字节）：GitHub 不返回超过 1MB 文件的正文。"
        )

    try:
        # GitHub 每 60 个字符插一个换行，不用先清理：b64decode 默认会丢掉所有不在
        # 字母表里的字符。解完是文本文件才算数，二进制文件在这里被挡下。
        content = base64.b64decode(raw).decode("utf-8")
    except ValueError as error:
        # binascii.Error（Base64 不合法）和 UnicodeDecodeError（不是 UTF-8）都是
        # ValueError，对调用方也是同一件事：这份内容解不出文本。
        raise GitHubAPIError(f"{path!r} 的内容解不出文本：{error}") from error

    # 用 GitHub 回的规范路径：LLM 写 "./app/x.py" 也能读到，但 Evidence 的 location
    # 应该记规范的那个。
    return DocumentContent(path=payload.get("path") or path, content=content)
