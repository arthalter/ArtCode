"""Small desktop bridge over the existing Application; not the ch15 v1 protocol."""
from __future__ import annotations

import asyncio
from dataclasses import fields, is_dataclass
import json
from pathlib import Path
import signal
import sys
from uuid import uuid4

from artcode._application import LocalApplication
from artcode.core.application import ApplicationOptions, ExitRequested
from artcode.core.model import ProtocolMetadata
from artcode.core.session import SessionSelection
from artcode.core.tool import ApprovalChoice


def public(value):
    """Project existing values, excluding model-only state and opaque metadata."""
    if isinstance(value, ProtocolMetadata):
        return None
    if is_dataclass(value):
        return {"type": type(value).__name__, **{
            f.name: public(getattr(value, f.name)) for f in fields(value)
            if f.name not in {"metadata", "pending_notices"}
        }}
    if isinstance(value, dict):
        return {str(k): public(v) for k, v in value.items() if k != "metadata"}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [public(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


class DesktopBridge:
    def __init__(self, send, factory=LocalApplication.create):
        self.send = send
        self.factory = factory
        self.application = None
        self.active = None
        self.pending = {}
        self.initialized = False
        self.closing = False
        self.cleanup = None
        self.exiting_application = False
        self.stopped = asyncio.Event()

    def event(self, kind, **data):
        self.send({"jsonrpc": "2.0", "method": "event", "params": {"kind": kind, **public(data)}})

    async def ask(self, kind, value, choices):
        key = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        prompt = {"id": key, "kind": kind, "value": public(value), "choices": choices}
        self.pending[key] = (future, prompt)
        self.event("interaction", id=key, prompt_kind=kind, value=prompt["value"], choices=choices)
        try:
            return await future
        finally:
            self.pending.pop(key, None)
            self.event("interaction_resolved", id=key)

    async def approve(self, request):
        return ApprovalChoice(await self.ask("tool", request, [v.value for v in ApprovalChoice]))

    async def approve_mcp_server(self, name, summary):
        return await self.ask("mcp", {"name": name, "summary": summary}, ["allow", "deny"]) == "allow"

    async def confirm_worktree_discard(self, handoff):
        return await self.ask("discard", handoff, ["discard", "keep"]) == "discard"

    async def choose_active_task_exit(self, tasks):
        return await self.ask("exit", tasks, ["wait", "cancel", "return"])

    def snapshot(self, history=True):
        if self.application is None or self.exiting_application:
            return None
        result = public(self.application.snapshot())
        if not history:
            result["session"].pop("facts", None)
        return result

    def start(self, work):
        if self.closing or (self.active is not None and not self.active.done()):
            raise ValueError("BUSY：请等待当前操作结束。")
        operation = uuid4().hex

        async def execute():
            self.event("busy", busy=True)
            try:
                await work()
            except asyncio.CancelledError:
                self.event("output", output={"type": "ErrorOutput", "message": "操作已取消。"})
            except Exception as exc:
                self.event("output", output={"type": "ErrorOutput", "message": str(exc)})
            finally:
                self.event("snapshot", snapshot=self.snapshot())
                self.event("busy", busy=False, operation=operation)

        self.active = asyncio.create_task(execute())
        return {"operation": operation}

    async def dispatch(self, method, params):
        if method == "initialize":
            if params.get("protocol") != "artcode-desktop/0.1":
                raise ValueError("桌面协议版本不匹配。")
            self.initialized = True
            return {"protocol": "artcode-desktop/0.1"}
        if not self.initialized:
            raise ValueError("请先初始化连接。")
        if method == "open":
            if self.application is not None:
                raise ValueError("请先关闭当前项目。")
            workspace = Path(params["workspace"]).expanduser().resolve()
            if not workspace.is_dir():
                raise ValueError("项目目录不存在。")
            home = Path.home() / ".artcode"
            config = Path(params.get("config") or home / "config.yml").expanduser().resolve()
            selection = SessionSelection.new() if params.get("new") else SessionSelection.latest()

            async def opening():
                self.application = await self.factory(
                    ApplicationOptions(workspace, config, home, selection), interaction=self
                )

            return self.start(opening)
        if method == "answer":
            item = self.pending.get(params.get("id"))
            if item is None or item[0].done():
                raise ValueError("审批已经结束。")
            if params.get("choice") not in item[1]["choices"]:
                raise ValueError("无效的审批选项。")
            item[0].set_result(params["choice"])
            return {"ok": True}
        if method == "snapshot":
            return {"snapshot": self.snapshot(), "busy": bool(self.active and not self.active.done()),
                    "interactions": [item[1] for item in self.pending.values()]}
        if method == "cancel":
            if self.application is not None:
                self.application.cancel_current()
            # Also interrupt preparation and pending UI interactions, before a RunControl exists.
            if self.active is not None and not self.active.done():
                self.active.cancel()
                return {"requested": True}
            return {"requested": False}
        if method == "close":
            if not self.closing:
                self.closing = True
                asyncio.create_task(self.shutdown())
            return {"ok": True}
        if self.application is None:
            raise ValueError("请先打开项目。")
        if method == "input":
            text = params.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
                raise ValueError("请输入 1～100000 个字符。")

            async def run():
                self.exiting_application = text.strip().casefold() == "/exit"
                try:
                    async for output in self.application.stream(text):
                        self.event("output", output=output)
                        if isinstance(output, ExitRequested):
                            self.application = None
                finally:
                    self.exiting_application = False

            return self.start(run)
        if method == "background":
            return {"requested": self.application.background_current_task()}
        raise ValueError("未知方法。")

    async def request(self, message):
        request_id = message.get("id") if isinstance(message, dict) else None
        try:
            if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
                    or not isinstance(request_id, str) or not isinstance(message.get("params", {}), dict)):
                raise ValueError("无效的 JSON-RPC 请求。")
            result = await self.dispatch(message.get("method"), message.get("params", {}))
            self.send({"jsonrpc": "2.0", "id": request_id, "result": public(result)})
        except Exception as exc:
            self.send({"jsonrpc": "2.0", "id": request_id,
                       "error": {"code": -32000, "message": str(exc)}})

    async def shutdown(self):
        self.closing = True
        if self.cleanup is None:
            self.cleanup = asyncio.create_task(self._cleanup())
        await asyncio.shield(self.cleanup)

    async def _cleanup(self):
        try:
            if self.active is not None and not self.active.done():
                self.active.cancel()
                await asyncio.gather(self.active, return_exceptions=True)
            if self.application is not None:
                application = self.application
                self.application = None
                await application.close()
        finally:
            self.stopped.set()

    async def observe(self):
        previous = None
        while not self.stopped.is_set():
            if self.application is not None and not self.closing and not self.exiting_application:
                snapshot = self.snapshot(history=False)
                if snapshot != previous:
                    self.event("status", snapshot=snapshot)
                    previous = snapshot
            await asyncio.sleep(0.75)


async def serve():
    wire = sys.stdout
    sys.stdout = sys.stderr

    def send(message):
        wire.write(json.dumps(message, ensure_ascii=False) + "\n")
        wire.flush()

    bridge = DesktopBridge(send)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, bridge.stopped.set)
    reader = asyncio.StreamReader(limit=2 * 1024 * 1024)
    transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)

    async def read():
        while line := await reader.readline():
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "无效 JSON。"}})
                continue
            await bridge.request(message)

    reading = asyncio.create_task(read())
    observing = asyncio.create_task(bridge.observe())
    stopping = asyncio.create_task(bridge.stopped.wait())
    try:
        await asyncio.wait((reading, observing, stopping), return_when=asyncio.FIRST_COMPLETED)
    finally:
        transport.close()
        for task in (reading, observing, stopping):
            task.cancel()
        await asyncio.gather(reading, observing, stopping, return_exceptions=True)
        await bridge.shutdown()


if __name__ == "__main__":
    asyncio.run(serve())
