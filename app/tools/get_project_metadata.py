"""获取仓库基础元数据的 Tool。

走 GitHub REST API：

    GET /repos/{owner}/{repo}

只做字段映射：GitHub 的原始 JSON → ProjectMetadata。不分析、不概括、不生成
Evidence —— 那些是 Agent 和 LLM 的事。schema 里没有的字段（forks、license 等）
一律丢掉，Tool 的产出必须有稳定的形状。

认证、失败分类、请求怎么发，都在 _github 里。
"""

from app.config import load_github_settings
from app.schemas.project import ProjectMetadata
from app.tools._github import (
    GITHUB_API_ROOT,
    GitHubAPIError,
    get_json,
    parse_repo,
    quote,
)


def get_project_metadata(url: str) -> ProjectMetadata:
    """返回 url 所指仓库的基础元数据。"""
    owner, repo = parse_repo(url)
    api_url = f"{GITHUB_API_ROOT}/repos/{quote(owner)}/{quote(repo)}"

    # token 只在这里取一次，读 env 是 app/config.py 的事
    token = load_github_settings().token
    payload = get_json(api_url, token)

    name = payload.get("name")
    stars = payload.get("stargazers_count")
    if not isinstance(name, str) or not name or not isinstance(stars, int):
        # 这两个字段 GitHub 一定会给。真缺了说明响应形状变了，此时填默认值就是报假
        # 事实 —— stars 落成 0，读的人会当成「这个项目没人 star」。
        raise GitHubAPIError(
            f"{owner}/{repo} 的响应里读不到 name / stargazers_count，"
            f"GitHub 的返回形状可能变了"
        )

    # 其余字段都有正当的「没有」：仓库可以不写简介、不打 topics、主要语言判断不出来
    # （GitHub 给 null）。schema 里它们是 str / list，按 schema 的定义落成空值，
    # 不脑补内容 —— 补出来的简介和话题就是编的。
    topics = payload.get("topics")
    return ProjectMetadata(
        name=name,
        description=payload.get("description") or "",
        # html_url 是 GitHub 给的规范地址（仓库改过名时和入参不同）；没给就用刚解析
        # 出来的 owner/repo 拼一个 —— 这个字段可推导，不值得为它报错。
        url=payload.get("html_url") or f"https://github.com/{owner}/{repo}",
        # language 为 null 正是 schema 里 None 的含义：判断不出主要语言
        language=payload.get("language"),
        stars=stars,
        topics=(
            [item for item in topics if isinstance(item, str)]
            if isinstance(topics, list)
            else []
        ),
    )
