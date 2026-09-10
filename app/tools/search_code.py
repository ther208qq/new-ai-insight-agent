"""在仓库代码中搜索关键词的 Tool。

当前搜的是 _mock_repo 里的固定内容，不访问 GitHub API。
owner / repo 先保留在签名里，等接入真实 API 时才会用到。

搜不到结果是正常结果（返回空 matches），不是错误 —— 和 get_file 读不到文件
不一样：文件不存在说明这个 Tool 没用上，搜不到只说明换个词再试。
"""

from app.schemas.search import CodeMatch, SearchResult
from app.tools._mock_repo import MOCK_FILES

# 单次搜索的匹配数上限。结果太多对 LLM 没帮助，反而挤占 Context。
SEARCH_LIMIT = 20


def search_code(owner: str, repo: str, query: str) -> SearchResult:
    """在仓库代码里搜索关键词，返回匹配到的行。"""
    matches: list[CodeMatch] = []
    truncated = False

    # 按路径排序，保证同样的 query 每次得到同样的结果
    for path, content in sorted(MOCK_FILES.items()):
        for line_number, line in enumerate(content.splitlines(), start=1):
            if query.lower() not in line.lower():
                continue
            if len(matches) >= SEARCH_LIMIT:
                truncated = True
                break
            matches.append(
                CodeMatch(path=path, line_number=line_number, line=line.strip())
            )
        if truncated:
            break

    return SearchResult(query=query, matches=matches, truncated=truncated)
