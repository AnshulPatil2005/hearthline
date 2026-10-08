from scripts import export_api


def test_committed_api_files_match_the_code():
    """docs/api is what APIMatic and Postman read. Regenerate with: uv run python -m scripts.export_api"""
    for path, text in export_api.files().items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is out of date"


def test_every_operation_has_an_id_and_a_description_for_the_sdks():
    for path, ops in export_api.openapi()["paths"].items():
        for method, op in ops.items():
            assert op.get("operationId"), f"{method} {path} needs an operationId"
            assert op.get("summary") or op.get("description"), f"{method} {path} needs a description"
