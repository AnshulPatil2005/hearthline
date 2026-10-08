"""Write the Public API v1 contract: an OpenAPI file (APIMatic generates the SDKs and docs from it) and a
Postman collection. Run after changing /v1:  uv run python -m scripts.export_api
A test fails if the committed files are out of date."""

import json
from pathlib import Path

from app.main import app

DOCS = Path(__file__).resolve().parents[2] / "docs" / "api"
SERVERS = [
    {"url": "https://hearthline-api.onrender.com", "description": "Hosted demo (PayPal sandbox)"},
    {"url": "http://localhost:8000", "description": "Local development"},
]


def _refs(node, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[1])
        for v in node.values():
            _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)


def openapi() -> dict:
    full = app.openapi()
    paths = {p: v for p, v in full["paths"].items() if p.startswith("/v1/")}
    schemas = full["components"]["schemas"]
    needed: set[str] = set()
    _refs(paths, needed)
    while True:  # schemas referenced by schemas
        more: set[str] = set()
        for name in needed:
            _refs(schemas[name], more)
        if more <= needed:
            break
        needed |= more
    return {
        "openapi": full["openapi"],
        "info": {
            "title": "Hearthline Public API",
            "version": "1.0.0",
            "description": (
                "Find verified families' Rebuild Registries and local businesses' Reopen Funds after a disaster, "
                "check essential prices against their pre-disaster baseline, and prepare gifts. Preparing a gift "
                "returns a PayPal approval link: a person approves every payment, nothing is charged before that. "
                "The same operations are MCP tools at /mcp."
            ),
            "license": {"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        },
        "servers": SERVERS,
        "tags": [{"name": "Public API v1", "description": "No login needed."}],
        "paths": paths,
        "components": {"schemas": {k: schemas[k] for k in sorted(needed)}},
    }


def _example(schema: dict, schemas: dict) -> object:
    if "$ref" in schema:
        return _example(schemas[schema["$ref"].rsplit("/", 1)[1]], schemas)
    if "examples" in schema:
        return schema["examples"][0]
    if "anyOf" in schema:
        return _example(next(s for s in schema["anyOf"] if s.get("type") != "null"), schemas)
    if schema.get("type") == "object":
        return {
            k: _example(v, schemas) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [k])
        }
    return {"string": "", "integer": 0, "number": 0, "boolean": False, "array": []}.get(schema.get("type"), None)


def postman(spec: dict) -> dict:
    schemas = spec["components"]["schemas"]
    items = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            url_path = path.replace("{", ":").replace("}", "")
            params = [p for p in op.get("parameters", []) if p["in"] == "path"]
            request = {
                "method": method.upper(),
                "header": [{"key": "Content-Type", "value": "application/json"}],
                "url": {
                    "raw": "{{baseUrl}}" + url_path,
                    "host": ["{{baseUrl}}"],
                    "path": [s for s in url_path.split("/") if s],
                    "variable": [
                        {"key": p["name"], "value": "rivera-family" if p["name"] == "slug" else ""} for p in params
                    ],
                },
                "description": op.get("description") or op.get("summary", ""),
            }
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body:
                request["body"] = {"mode": "raw", "raw": json.dumps(_example(body, schemas), indent=2)}
            items.append({"name": op.get("summary") or op["operationId"], "request": request})
    return {
        "info": {
            "name": "Hearthline Public API v1",
            "description": spec["info"]["description"],
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [{"key": "baseUrl", "value": SERVERS[0]["url"]}],
        "item": items,
    }


def files() -> dict[Path, str]:
    spec = openapi()
    return {
        DOCS / "hearthline-v1.openapi.json": json.dumps(spec, indent=2) + "\n",
        DOCS / "hearthline-v1.postman_collection.json": json.dumps(postman(spec), indent=2) + "\n",
    }


if __name__ == "__main__":
    DOCS.mkdir(parents=True, exist_ok=True)
    for path, text in files().items():
        path.write_text(text, encoding="utf-8")
        print("wrote", path)
