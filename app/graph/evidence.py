"""Tool 产出 → Evidence → State 的转换。

Evidence 必须由代码生成，不让 LLM 参与：它是事实来源。
所以 content 直接取自 Tool 返回的原始数据，不做概括、不做改写，
唯一允许的加工是截断（等接真实 API 时再加）。
"""

from app.graph.state import KnowledgeProcessState
from app.schemas.document import DocumentContent
from app.schemas.evidence import Evidence, EvidenceType
from app.schemas.project import ProjectMetadata
from app.schemas.search import SearchResult
from app.schemas.structure import ProjectStructure

# 当前所有 Tool 都取自 GitHub；等出现别的数据源时再改成按 Tool 声明
GITHUB_SOURCE = "github"

# Tool 的产出被截断时会丢内容。截断只影响「LLM 看到多少」，但 LLM 会把
# 「没看到」当成「不存在」，进而少调工具或误判信息已经足够 —— 所以必须
# 把「这份证据不完整」写进 content，不能悄悄截断。
_TRUNCATION_NOTICE = "（内容过长，已截断，以上不是全部）"

_NO_SEARCH_MATCH = "（没有匹配到任何内容）"

README_FILENAMES = frozenset(
    {"readme", "readme.md", "readme.rst", "readme.txt", "readme.markdown"}
)


def metadata_to_evidence(metadata: ProjectMetadata) -> Evidence:
    """ProjectMetadata → Evidence。

    content 是元数据的原始 JSON：结构化数据序列化后才是完整的、无歧义的事实，
    location 用仓库 URL，方便回溯到具体是哪个仓库。
    """
    return Evidence(
        source=GITHUB_SOURCE,
        location=metadata.url,
        content=metadata.model_dump_json(indent=2),
        evidence_type="metadata",
    )


def document_to_evidence(
    document: DocumentContent,
    evidence_type: EvidenceType | None = None,
) -> Evidence:
    """DocumentContent → Evidence。

    DocumentContent 被 README 和普通源码文件共用，所以类型默认按文件名推断
    （README → readme，其余 → code）；调用方明确知道内容性质时可以覆盖。
    """
    if evidence_type is None:
        evidence_type = "readme" if _is_readme(document.path) else "code"

    content = document.content
    if document.truncated:
        content = f"{content}\n{_TRUNCATION_NOTICE}"

    return Evidence(
        source=GITHUB_SOURCE,
        location=document.path,
        content=content,
        evidence_type=evidence_type,
    )


def structure_to_evidence(structure: ProjectStructure) -> Evidence:
    """ProjectStructure → Evidence。

    location 不指向具体某个文件，而是用仓库根目录的标记（"."）表示
    「这是整个仓库的目录」—— 它描述的是仓库整体，不是某一处内容。
    """
    content = "\n".join(structure.paths)
    if structure.truncated:
        content = f"{content}\n{_TRUNCATION_NOTICE}"

    return Evidence(
        source=GITHUB_SOURCE,
        location=".",
        content=content,
        evidence_type="structure",
    )


def search_to_evidence(result: SearchResult) -> Evidence:
    """SearchResult → Evidence。

    location 用搜索词而不是仓库根：这条 Evidence 描述的是「搜这个词得到了什么」，
    同一轮调查里搜两次不同关键词，是两条不同的证据。

    搜不到结果是**有效结果**（说明这个词不在仓库里），不能变成空 content ——
    LLM 需要区分「搜过了没有」和「还没搜过」。
    """
    if result.matches:
        content = "\n".join(
            f"{match.path}:{match.line_number}: {match.line}" for match in result.matches
        )
        if result.truncated:
            content = f"{content}\n{_TRUNCATION_NOTICE}"
    else:
        content = _NO_SEARCH_MATCH

    return Evidence(
        source=GITHUB_SOURCE,
        location=f"search:{result.query}",
        content=content,
        evidence_type="search",
    )


def record_evidence(
    state: KnowledgeProcessState, *evidences: Evidence
) -> KnowledgeProcessState:
    """把 Evidence 追加进 state.evidence，返回新的 state（不修改传入对象）。"""
    return state.model_copy(
        update={"evidence": [*state.evidence, *evidences]},
    )


def _is_readme(path: str) -> bool:
    return path.rsplit("/", 1)[-1].lower() in README_FILENAMES
