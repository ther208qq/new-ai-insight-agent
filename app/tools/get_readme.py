"""获取仓库 README 的 Tool。

走 GitHub REST API：

    GET /repos/{owner}/{repo}/readme

用它而不是自己拼 README.md：README 到底叫什么、在哪儿，由 GitHub 去找
（README.rst、docs/README.md 都认），自己拼就是猜，猜错只会得到 404。

正文以 Base64 回来，这里解码成 UTF-8 文本再包成 DocumentContent —— GitHub 的
原始 JSON 不往上抛，Tool 的产出必须有稳定的形状。路径同理，用 GitHub 回的
path / name，不猜。

内容**不在这里截断**：截断是 Context 层的职责（见 graph/context 的
MAX_EVIDENCE_CHARS），Tool 只负责如实取回 —— 和 get_file 一致。
"""

import base64

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


def get_readme(url: str) -> DocumentContent:
    """返回 url 所指仓库的 README 内容。

    README 不存在时抛错，不返回空的 DocumentContent：空内容和「这个仓库没有
    README」是两回事，混在一起会让 LLM 以为它读到的是一份空文档。
    """
    owner, repo = parse_repo(url)
    api_url = f"{GITHUB_API_ROOT}/repos/{quote(owner)}/{quote(repo)}/readme"

    # token 只在这里取一次，读 env 是 app/config.py 的事
    token = load_github_settings().token

    try:
        payload = get_json(api_url, token)
    except RepositoryNotFoundError as error:
        # 仓库不存在和「仓库里没有 README」，GitHub 回的都是 404，分不出来 ——
        # 只说其中一个会把人引到错的方向。子类原样抛回去，别打散成父类。
        raise RepositoryNotFoundError(
            f"{owner}/{repo} 里读不到 README（GitHub 返回 404）："
            f"仓库本身不存在，或者它没有 README。"
        ) from error

    if payload.get("type") != "file":
        # README 只可能是文件。能走到这里的 type 只剩 file / symlink / submodule，
        # 后两者给的「正文」其实是链接目标，当文档返回等于给了份假 README。
        raise GitHubAPIError(
            f"{owner}/{repo} 的 README 不是普通文件（type={payload.get('type')!r}）"
        )

    raw = payload.get("content")
    if payload.get("encoding") != "base64" or raw is None:
        # 超过 1MB 的 README，GitHub 只给元数据、不给正文。照常往下走会解出一个
        # 空字符串 —— 那是个假 README，比报错更糟。
        raise GitHubAPIError(
            f"{owner}/{repo} 的 README 正文没拿到"
            f"（encoding={payload.get('encoding')!r}，size={payload.get('size')} 字节）："
            f"GitHub 不返回超过 1MB 文件的正文。"
        )

    try:
        # GitHub 每 60 个字符插一个换行，不用先清理：b64decode 默认会丢掉所有不在
        # 字母表里的字符。解完是文本才算数，二进制在这里被挡下。
        content = base64.b64decode(raw).decode("utf-8")
    except ValueError as error:
        # binascii.Error（Base64 不合法）和 UnicodeDecodeError（不是 UTF-8）都是
        # ValueError，对调用方也是同一件事：这份内容解不出文本。
        raise GitHubAPIError(f"{owner}/{repo} 的 README 解不出文本：{error}") from error

    # 用 GitHub 回的规范路径：它才是 README 的真实位置，也是进 Evidence 的 location
    path = payload.get("path") or payload.get("name")
    if not isinstance(path, str) or not path:
        raise GitHubAPIError(f"{owner}/{repo} 的 README 响应里没有 path / name")

    return DocumentContent(path=path, content=content)
