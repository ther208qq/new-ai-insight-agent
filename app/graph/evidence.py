"""Tool 产出 → Evidence → State 的转换。

Evidence 必须由代码生成，不让 LLM 参与：它是事实来源。
所以 content 直接取自 Tool 返回的原始数据，不做概括、不做改写，
唯一允许的加工是截断（等接真实 API 时再加）。
"""

from app.graph.state import KnowledgeProcessState
from app.schemas.document import DocumentContent
from app.schemas.evidence import Evidence, EvidenceType
from app.schemas.project import ProjectMetadata

# 当前所有 Tool 都取自 GitHub；等出现别的数据源时再改成按 Tool 声明
GITHUB_SOURCE = "github"

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

    return Evidence(
        source=GITHUB_SOURCE,
        location=document.path,
        content=document.content,
        evidence_type=evidence_type,
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
