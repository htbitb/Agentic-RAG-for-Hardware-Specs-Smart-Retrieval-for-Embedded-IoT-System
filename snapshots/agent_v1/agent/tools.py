"""MCP client hub (plan 3.1): connects the agent to BOTH MCP servers, discovers
their tools via tools/list, and executes calls with least-privilege, timeouts,
retries and audit logging (R2, R6, AT2).

transport="stdio"  : spawns `python -m mcp_servers.<server>` as subprocesses and
                     speaks real MCP (JSON-RPC over stdio) - default.
transport="inproc" : imports the same tool functions directly (fast path used
                     for large evaluation runs; identical results, no IPC).
"""
import asyncio
import json
import sys
import threading
import time

import config
from agent import approval, audit
from agent.guardrail import sanitize_observation

SERVERS = {
    "text-manual": "mcp_servers.text_manual_server",
    "table-register": "mcp_servers.table_register_server",
}
# R2: documented permission level of every tool (least privilege).
PERMISSIONS = {
    "search_manual": "read-only", "naive_search": "read-only", "get_chunk_context": "read-only",
    "list_documents": "read-only", "query_pin_alternate_function": "read-only",
    "get_register_bitfields": "read-only", "get_electrical_specs": "read-only",
    "check_logic_level_compatibility": "read-only", "list_chips": "read-only",
    "write_config_file": "irreversible-write",
}
BASELINE_ONLY = {"naive_search"}  # hidden from the agent


class ToolHub:
    def __init__(self, transport: str = "stdio", disabled_servers: tuple = (), session_id: str = "default",
                 sanitize: bool = True):
        self.transport = transport
        self.sanitize = sanitize
        self.disabled = set(disabled_servers)
        self.session_id = session_id
        self.specs: list[dict] = []
        self.owner: dict[str, str] = {}
        self.stats = {"calls": 0, "errors": 0, "retries": 0}
        if transport == "stdio":
            try:
                import mcp  # noqa: F401
                self._start_stdio()
            except ImportError:
                print("[hub] `mcp` package not installed; falling back to in-process MCP transport", file=sys.stderr)
                self.transport = "inproc"
                self._start_inproc()
        else:
            self._start_inproc()
        self.specs.append(approval.WRITE_TOOL_SPEC)
        self.owner["write_config_file"] = "local-guarded"

    # ------------------------------------------------------------ in-process
    def _start_inproc(self):
        from mcp_servers import table_register_server as tr
        from mcp_servers import text_manual_server as tm
        self._fn = {}
        for server, mod in (("text-manual", tm), ("table-register", tr)):
            if server in self.disabled:
                continue
            for tool in asyncio.run(mod.mcp.list_tools()):
                self._register(server, tool.name, tool.description, tool.inputSchema)
                self._fn[tool.name] = getattr(mod, tool.name)

    # ----------------------------------------------------------------- stdio
    def _start_stdio(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.sessions = {}
        asyncio.run_coroutine_threadsafe(self._connect_all(), self.loop).result(timeout=180)

    async def _serve(self, name, module, ready):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable, args=["-m", module], cwd=str(config.ROOT))
        try:
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    tools = (await s.list_tools()).tools  # MCP tools/list discovery
                    self.sessions[name] = s
                    ready.set_result(tools)
                    await self._stop.wait()
        except Exception as exc:  # server failed to start -> agent continues without it (AT2)
            if not ready.done():
                ready.set_exception(exc)

    async def _connect_all(self):
        self._stop = asyncio.Event()
        self._tasks = []
        for name, module in SERVERS.items():
            if name in self.disabled:
                continue
            ready = self.loop.create_future()
            self._tasks.append(asyncio.create_task(self._serve(name, module, ready)))
            try:
                tools = await asyncio.wait_for(ready, timeout=170)
                for t in tools:
                    self._register(name, t.name, t.description, t.inputSchema)
                audit.log("mcp_server_connected", server=name, tools=[t.name for t in tools])
            except Exception as exc:
                audit.log("mcp_server_failed", server=name, error=str(exc))
                print(f"[hub] MCP server {name} unavailable: {exc}", file=sys.stderr)

    def _register(self, server, name, desc, schema):
        if name in BASELINE_ONLY:
            self.owner[name] = server
            return
        self.specs.append({"name": name, "description": desc, "inputSchema": schema})
        self.owner[name] = server

    # ------------------------------------------------------------------ call
    def tool_names(self):
        return [s["name"] for s in self.specs]

    def call(self, name: str, args: dict) -> dict:
        """Execute one tool call with permission check, timeout, retry (read-only only), sanitization, audit."""
        self.stats["calls"] += 1
        perm = PERMISSIONS.get(name)
        if name not in self.owner or perm is None:
            self.stats["errors"] += 1
            audit.log("tool_denied", tool=name, reason="unknown or disabled tool", session=self.session_id)
            return {"error": f"tool {name!r} is not available"}
        if perm == "irreversible-write":
            res = approval.request(args.get("filename", ""), args.get("content", ""), self.session_id)
            audit.log("tool_call", tool=name, permission=perm, args={"filename": args.get("filename")},
                      status=res["status"], session=self.session_id)
            return res
        t0, attempt, result = time.time(), 0, None
        while True:
            try:
                result = self._invoke(name, args)
                break
            except Exception as exc:
                attempt += 1
                if attempt > config.TOOL_RETRIES:  # read-only tools are idempotent -> safe to retry
                    self.stats["errors"] += 1
                    result = {"error": f"{type(exc).__name__}: {exc}", "retries": attempt - 1}
                    break
                self.stats["retries"] += 1
                time.sleep(0.2 * attempt)
        result, flags = sanitize_observation(result) if self.sanitize else (result, [])
        if flags:
            result["security_flags"] = flags
            audit.log("indirect_injection_neutralised", tool=name, flags=flags, session=self.session_id)
        audit.log("tool_call", tool=name, permission=perm, server=self.owner[name], args=args,
                  latency_ms=round((time.time() - t0) * 1000), error=result.get("error"), session=self.session_id)
        return result

    def _invoke(self, name, args):
        if self.transport == "inproc":
            return self._fn[name](**args)
        server = self.owner[name]
        if server not in self.sessions:
            raise RuntimeError(f"MCP server {server} not connected")
        fut = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(self.sessions[server].call_tool(name, arguments=args), config.TOOL_TIMEOUT_S), self.loop)
        res = fut.result(timeout=config.TOOL_TIMEOUT_S + 5)
        text = res.content[0].text if res.content else "{}"
        if res.isError:
            return {"error": text}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "malformed tool output", "raw": text[:500]}

    def raw_call(self, name, args):
        """Baseline-only access (e.g. naive_search) without agent bookkeeping."""
        return self._invoke(name, args)

    def close(self):
        if self.transport == "stdio" and hasattr(self, "_stop"):
            async def _shutdown():
                self._stop.set()
                await asyncio.gather(*self._tasks, return_exceptions=True)
            try:
                asyncio.run_coroutine_threadsafe(_shutdown(), self.loop).result(timeout=15)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
