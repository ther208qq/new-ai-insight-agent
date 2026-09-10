"""读取仓库中某个文件内容的 Tool。

当前读的是 _mock_repo 里的固定内容，不访问 GitHub API。
owner / repo 先保留在签名里，等接入真实 API 时才会用到。

路径读不到时抛 FileNotFoundError（而不是返回空内容）：空内容和「文件不存在」
是两回事，混在一起会让 LLM 以为自己读到了一个空文件。
"""

from app.schemas.document import DocumentContent
from app.tools._mock_repo import MOCK_FILES


def get_file(owner: str, repo: str, path: str) -> DocumentContent:
    """返回仓库中指定文件的内容。"""
    normalized = _normalize(path)

    if normalized not in MOCK_FILES:
        raise FileNotFoundError(
            f"文件不存在: {path!r}；当前仓库可读的文件有 {sorted(MOCK_FILES)}"
        )

    return DocumentContent(
        path=normalized,
        content=MOCK_FILES[normalized],
        truncated=False,
    )


def _normalize(path: str) -> str:
    """把 LLM 可能写歪的路径收敛成 MOCK_FILES 里的键。

    调用方是 LLM，路径写法不受控（"./src/a.py"、"/src/a.py" 都合理），
    为这个差别让整轮调查失败不值得，所以先去掉前缀再查。
    """
    return path.strip().lstrip("/").removeprefix("./")
