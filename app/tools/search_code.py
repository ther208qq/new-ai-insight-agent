"""在仓库代码中搜索关键词的 Tool。

走 GitHub 的代码搜索接口：

    GET https://api.github.com/search/code?q={query}+repo:{owner}/{repo}

⚠️ 这个接口**必须带 token**：匿名调用直接 401，和另外两个 Tool 不一样。
它的限流也是独立的，认证用户 10 次/分钟（响应头 X-RateLimit-Resource: code_search），
比核心 API 的 5000 次/小时紧得多。

只负责「搜到什么」，不做语义判断。搜到候选文件之后，需要完整源码时由 Agent
再去调 get_file —— 这个接口给的是片段，不是整份文件。
"""

from app.config import load_github_settings
from app.schemas.search import CodeMatch, SearchResult
from app.tools._github import GITHUB_API_ROOT, get_json, parse_repo

# 匹配条数上限。搜索结果对 LLM 只是「往哪儿看」的线索，给太多反而挤占 Context。
SEARCH_LIMIT = 20

# 要 text-match 媒体类型才有片段：默认只返回命中了哪些文件，连那一行是什么都不给。
_TEXT_MATCH_ACCEPT = "application/vnd.github.text-match+json"

# GitHub 代码搜索不是按行返回的，它给的是一段围绕匹配的文本窗口（fragment），
# 匹配在窗口内的偏移由 matches[].indices 给出。行号就藏在这一层层相对位置里，
# 所以这个 Tool 拿不到绝对行号 —— CodeMatch.line_number 因此留空。
_SEARCH_URL = f"{GITHUB_API_ROOT}/search/code"


class EmptyQueryError(ValueError):
    """query 为空。

    不返回空结果：空结果对 LLM 的意思是「这个词不在仓库里」，而空 query 是
    「你没告诉我搜什么」，两件事完全不同。
    """

def search_code(url: str, query: str) -> SearchResult:
    """在仓库代码里搜索关键词，返回匹配到的行。"""
    owner, repo = parse_repo(url)

    query = query.strip()
    if not query:
        raise EmptyQueryError("query 不能为空：要搜什么关键词？")

    # token 只在这里取一次，读 env 是 app/config.py 的事
    token = load_github_settings().token

    payload = get_json(
        _SEARCH_URL,
        token,
        # 按 repo: 限定范围，不然搜的是整个 GitHub。urlencode 会把空格和 : / 都
        # 转义好，q 不能自己拼。
        params={"q": f"{query} repo:{owner}/{repo}", "per_page": str(SEARCH_LIMIT)},
        accept=_TEXT_MATCH_ACCEPT,
    )

    items = payload.get("items") or []
    matches = _to_matches(items)

    # 三种「不完整」共用一个字段如实报告，漏报会让 LLM 以为搜到的就是全部：
    #   1. GitHub 自己说不完整（超时等）；
    #   2. 匹配的文件比给我们的多（total_count 是文件数，不是匹配数）；
    #   3. 我们按 SEARCH_LIMIT 切了一刀。
    truncated = (
        bool(payload.get("incomplete_results"))
        or payload.get("total_count", 0) > len(items)
        or len(matches) > SEARCH_LIMIT
    )

    return SearchResult(query=query, matches=matches[:SEARCH_LIMIT], truncated=truncated)


def _to_matches(items: list[dict]) -> list[CodeMatch]:
    """搜索结果 → CodeMatch 列表。

    一个文件可能给好几段 text_matches（同一个词出现多次），每段取出「匹配所在
    的那一行」，同一行的多次命中只留一条。
    """
    matches: list[CodeMatch] = []
    seen: set[tuple[str, str]] = set()

    for item in items:
        path = item.get("path")
        if not isinstance(path, str):
            continue

        for text_match in item.get("text_matches") or []:
            fragment = text_match.get("fragment")
            indices = text_match.get("matches") or []
            if not fragment or not indices:
                continue

            line = _matched_line(fragment, indices[0].get("indices", [0])[0])
            if not line or (path, line) in seen:
                continue

            seen.add((path, line))
            # 不传 line_number：这个接口不返回行号，编一个出来就是假数据
            matches.append(CodeMatch(path=path, line=line))

    return matches


def _matched_line(fragment: str, byte_offset: int) -> str:
    """片段里匹配所在的那一行。

    偏移是 **UTF-8 字节**偏移，不是字符偏移 —— 片段里有中文时两者会差开（每个
    汉字多算 2 个）。直接当字符下标用会落到后面好几行上，取出来的是别的行，
    而且完全看不出错。

    这是接口唯一给得出的「行」：片段内的相对位置。绝对行号算不出来 ——
    片段是从文件中间截的，截断点在文件的第几行接口不讲。
    """
    prefix = fragment.encode("utf-8")[:byte_offset].decode("utf-8", "ignore")
    lines = fragment.splitlines()
    index = prefix.count("\n")
    return lines[index].strip() if index < len(lines) else ""
