from app.schemas.project import ProjectMetadata
from app.tools.get_project_metadata import get_project_metadata


def test_返回_project_metadata():
    metadata = get_project_metadata("example", "demo-project")

    assert isinstance(metadata, ProjectMetadata)
    assert metadata.name == "demo-project"
    assert metadata.description == "一个用于演示 Knowledge Agent 的示例仓库。"
    assert metadata.url == "https://github.com/example/demo-project"
    assert metadata.language == "Python"
    assert metadata.stars == 128
    assert metadata.topics == ["demo", "agent", "llm"]


def test_language_允许为_None():
    metadata = ProjectMetadata(
        name="x",
        description="d",
        url="u",
        language=None,
        stars=0,
        topics=[],
    )

    assert metadata.language is None

