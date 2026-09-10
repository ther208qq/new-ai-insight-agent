from app.schemas.document import DocumentContent
from app.tools.get_readme import get_readme


def test_返回_document_content():
    readme = get_readme("example", "demo-project")

    assert isinstance(readme, DocumentContent)
    assert readme.path == "README.md"
    assert readme.truncated is False
    assert readme.content.startswith("# Demo Project")
    assert "## 安装" in readme.content
