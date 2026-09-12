"""获取仓库目录结构的 Tool。

两步：先问仓库的 default_branch，再按那个分支取一次递归树。
认证、失败分类、请求怎么发，都在 _github 里。
"""

from app.config import load_github_settings
from app.schemas.structure import ProjectStructure
from app.tools._github import (
    GITHUB_API_ROOT,
    GitHubAPIError,
    get_json,
    parse_repo,
    quote,
)

# 路径条数上限。GitHub 的树可以有十万条，而 Context 层只看得到前面几十条，
# 全量塞进 State 没有意义。GitHub 自己的截断由响应里的 truncated 报告。
MAX_PATHS = 2000


def get_project_structure(url: str) -> ProjectStructure:
    """返回 url 所指仓库的目录结构。

    先问 default_branch 再取树，不假设主干叫 main：猜错了会 404，而「这个仓库
    没有 main」会被误读成「仓库是空的」。
    """
    owner, repo = parse_repo(url)
    api_url = f"{GITHUB_API_ROOT}/repos/{quote(owner)}/{quote(repo)}"

    # token 只在这里取一次，读 env 是 app/config.py 的事
    token = load_github_settings().token

    branch = get_json(api_url, token).get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise GitHubAPIError(f"{owner}/{repo} 的响应里没有 default_branch")

    # recursive=1 一次拿全树；不带它只会返回顶层。分支名可以含 /，要转义
    payload = get_json(
        f"{api_url}/git/trees/{quote(branch)}", token, {"recursive": "1"}
    )

    entries = payload.get("tree")
    if not isinstance(entries, list):
        raise GitHubAPIError(f"{owner}/{repo} 的 tree 响应里没有 tree 数组")

    # 只取 path：schema 明写「不判断哪条是目录」，所以 tree 类型的条目不补尾斜杠。
    # 两种截断（GitHub 自己的、我们按 MAX_PATHS 切的）都如实报告 —— 漏报会让
    # LLM 把「没看到」当成「不存在」，进而误判信息已经够了。
    paths = [entry["path"] for entry in entries if isinstance(entry.get("path"), str)]
    truncated = bool(payload.get("truncated")) or len(paths) > MAX_PATHS
    return ProjectStructure(paths=paths[:MAX_PATHS], truncated=truncated)
