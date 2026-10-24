"""Lightweight MCP server helper supporting both official `mcp` FastMCP and zero-dependency in-process discovery."""
from dataclasses import dataclass
import inspect
from typing import Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    inputSchema: dict


class LocalMCP:
    """Fallback MCP registry when the `mcp` package is not installed."""

    def __init__(self, name: str):
        self.name = name
        self._tools: list[ToolSpec] = []

    def tool(self, description: str | None = None):
        def decorator(fn: Callable):
            sig = inspect.signature(fn)
            props = {}
            req = []
            for pname, param in sig.parameters.items():
                ann = param.annotation
                ptype = "string"
                if ann in (int, int | None):
                    ptype = "integer"
                elif ann in (float, float | None):
                    ptype = "number"
                elif ann in (bool, bool | None):
                    ptype = "boolean"
                props[pname] = {"type": ptype}
                if param.default is inspect.Parameter.empty:
                    req.append(pname)
            schema = {"type": "object", "properties": props}
            if req:
                schema["required"] = req
            self._tools.append(ToolSpec(
                name=fn.__name__,
                description=description or (fn.__doc__ or "").strip(),
                inputSchema=schema,
            ))
            return fn
        return decorator

    async def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def run(self):
        raise RuntimeError("Install the `mcp` package (`pip install mcp`) to run MCP servers over stdio.")


def create_mcp(name: str):
    try:
        from mcp.server.fastmcp import FastMCP
        return FastMCP(name)
    except ImportError:
        return LocalMCP(name)
