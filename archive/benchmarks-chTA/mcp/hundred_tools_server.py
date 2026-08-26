from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP


TARGETS = (
    ("lookup_customer_risk", "Look up a customer fraud risk score", "customer_id"),
    ("summarize_release_notes", "Summarize product release notes", "version"),
    ("calculate_shipping_quote", "Calculate a shipping quote", "postal_code"),
    ("inspect_build_artifact", "Inspect a build artifact checksum", "artifact_id"),
    ("resolve_incident_owner", "Resolve the owner of an incident", "incident_id"),
)


def build_server() -> FastMCP:
    server = FastMCP("ArtCode chTA 120-tool fixture", log_level="ERROR")
    for name, description, field in TARGETS:

        def make_target(tool_name: str, field_name: str):
            def target(value: str) -> str:
                return json.dumps(
                    {"tool": tool_name, "field": field_name, "value": value},
                    sort_keys=True,
                )

            return target

        target = make_target(name, field)
        target.__name__ = name
        server.tool(name=name, description=f"{description}; input field {field}")(
            target
        )

    for index in range(115):
        name = f"catalog_tool_{index:03d}"

        def make_generic(tool_index: int):
            def generic(query: str) -> str:
                return f"catalog:{tool_index:03d}:{query}"

            return generic

        generic = make_generic(index)
        generic.__name__ = name
        server.tool(
            name=name,
            description=f"Deterministic generic catalog operation number {index:03d}",
        )(generic)
    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
