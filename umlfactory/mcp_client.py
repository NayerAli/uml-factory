"""Appels aux outils du serveur MCP (lecture du .puml, écriture des sources)."""

from __future__ import annotations

from typing import Any

from mcp import Client


class McpToolError(RuntimeError):
    pass


async def _call(url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        async with Client(url) as client:
            result = await client.call_tool(tool, arguments)
    except Exception as exc:  # noqa: BLE001 - message clair quel que soit le détail du transport
        raise McpToolError(f"serveur MCP injoignable ou en erreur ({url}) : {exc}") from exc
    if getattr(result, "is_error", False):
        texts = [getattr(c, "text", "") for c in (result.content or [])]
        raise McpToolError(f"{tool} : {' '.join(t for t in texts if t) or 'erreur'}")
    return result.structured_content or {}


async def read_puml(url: str, path: str) -> str:
    return (await _call(url, "read_puml", {"path": path}))["text"]


async def write_sources(url: str, dest_dir: str, files: dict[str, str], overwrite: bool = False) -> list[str]:
    payload = {"dest_dir": dest_dir, "overwrite": overwrite,
               "files": [{"path": p, "content": c} for p, c in files.items()]}
    return list((await _call(url, "write_sources", payload))["written"])
