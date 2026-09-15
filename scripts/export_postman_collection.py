"""Convert the live OpenAPI schema into a Postman Collection v2.1 file, one
folder per tag, with example request bodies built from each endpoint's
schema so every request is ready to send with minimal editing.

Run with the API up: `python3 scripts/export_postman_collection.py`
Re-run any time the API's routes/schemas change -- nothing here is
hand-maintained, it's derived straight from /openapi.json.
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path


def resolve(schemas, ref):
    return schemas.get(ref.split("/")[-1], {})


def example_for_schema(schemas, schema, depth=0):
    if not schema or depth > 4:
        return None
    if "$ref" in schema:
        return example_for_schema(schemas, resolve(schemas, schema["$ref"]), depth + 1)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    any_of = schema.get("anyOf") or schema.get("oneOf")
    if any_of:
        for option in any_of:
            if option.get("type") != "null":
                return example_for_schema(schemas, option, depth + 1)
        return None
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        out = {k: example_for_schema(schemas, v, depth + 1) for k, v in props.items() if not required or k in required}
        if not out and props:
            key, sub = next(iter(props.items()))
            out[key] = example_for_schema(schemas, sub, depth + 1)
        return out
    if t == "array":
        item = example_for_schema(schemas, schema.get("items", {}), depth + 1)
        return [item] if item is not None else []
    if t == "string":
        if schema.get("enum"):
            return schema["enum"][0]
        if schema.get("format") == "date-time":
            return "2026-01-01T00:00:00Z"
        return "string"
    if t == "integer" or t == "number":
        return 0
    if t == "boolean":
        return True
    return None


def postman_url(base_url, path, params):
    postman_path = re.sub(r"\{(\w+)\}", r":\1", path)  # {deal_id} -> :deal_id
    variable = [{"key": p["name"], "value": f"<{p['name']}>"} for p in params if p.get("in") == "path"]
    return {"raw": "{{baseUrl}}" + postman_path, "host": ["{{baseUrl}}"],
            "path": [seg for seg in postman_path.split("/") if seg], "variable": variable}


def build_request(schemas, method, path, op):
    params = op.get("parameters", [])
    query = [{"key": p["name"], "value": f"<{p['name']}>", "disabled": not p.get("required", False)}
             for p in params if p.get("in") == "query"]
    url = postman_url("{{baseUrl}}", path, params)
    if query:
        url["query"] = query
        url["raw"] += "?" + "&".join(f"{q['key']}={q['value']}" for q in query)

    request = {"method": method.upper(), "header": [], "url": url,
               "description": op.get("description") or op.get("summary") or ""}

    body = op.get("requestBody")
    if body:
        content = body.get("content", {})
        if "application/json" in content:
            example = example_for_schema(schemas, content["application/json"].get("schema", {}))
            request["header"].append({"key": "Content-Type", "value": "application/json"})
            request["body"] = {"mode": "raw", "raw": json.dumps(example, indent=2),
                                "options": {"raw": {"language": "json"}}}
        elif "multipart/form-data" in content:
            schema = content["multipart/form-data"].get("schema", {})
            props = resolve(schemas, schema["$ref"]).get("properties", {}) if "$ref" in schema else schema.get("properties", {})
            request["body"] = {"mode": "formdata", "formdata": [
                {"key": k, "type": "file" if v.get("format") == "binary" else "text", "value": ""}
                for k, v in props.items()]}

    return {"name": op.get("summary") or f"{method.upper()} {path}", "request": request, "response": []}


def build_collection(spec, base_url):
    schemas = spec.get("components", {}).get("schemas", {})
    folders, order = {}, []
    for tag_meta in spec.get("tags", []):
        folders[tag_meta["name"]] = {"name": tag_meta["name"], "description": tag_meta.get("description", ""), "item": []}
        order.append(tag_meta["name"])
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tag = (op.get("tags") or ["untagged"])[0]
            if tag not in folders:
                folders[tag] = {"name": tag, "description": "", "item": []}
                order.append(tag)
            folders[tag]["item"].append(build_request(schemas, method, path, op))
    return {
        "info": {"name": spec["info"]["title"], "description": spec["info"].get("description", ""),
                  "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "variable": [{"key": "baseUrl", "value": base_url, "type": "string"}],
        "item": [folders[name] for name in order],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "api" / "postman_collection.json"))
    args = parser.parse_args()

    with urllib.request.urlopen(f"{args.base_url}/openapi.json") as response:
        spec = json.load(response)

    collection = build_collection(spec, args.base_url)
    Path(args.out).write_text(json.dumps(collection, indent=2))
    total = sum(len(f["item"]) for f in collection["item"])
    print(f"wrote {args.out}: {len(collection['item'])} folders, {total} requests")
