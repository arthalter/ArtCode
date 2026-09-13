"""Three focused checks for the new transport boundary; core behavior stays in its existing suite."""
import asyncio
from pathlib import Path

import pytest

from artcode.core.application import ApplicationSnapshot, TextOutput
from artcode.core.model import ProtocolMetadata, ToolRequest
from artcode.core.session import SessionSnapshot, ToolExchangeFact
from artcode.desktop_server import DesktopBridge, public


class ApplicationStub:
    def __init__(self, interaction):
        self.interaction = interaction
        self.closed = False

    def snapshot(self):
        return ApplicationSnapshot(Path('/tmp'), SessionSnapshot('test', 0, False, ()), None, None, (), False, self.closed)

    async def stream(self, text):
        yield TextOutput('开始', streaming=True)
        await self.interaction.ask('tool', {'target': 'test.txt'}, ['allow_once', 'deny_once'])
        yield TextOutput('完成', streaming=True)

    def cancel_current(self):
        return True

    async def close(self):
        assert not self.closed, 'cleanup must run exactly once'
        self.closed = True
        await asyncio.sleep(0)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_open_approval_busy_stream_and_close(tmp_path):
    messages = []

    async def factory(options, interaction):
        assert options.workspace == tmp_path
        await interaction.approve_mcp_server('test', 'startup approval')
        return ApplicationStub(interaction)

    bridge = DesktopBridge(messages.append, factory)
    await bridge.dispatch('initialize', {'protocol': 'artcode-desktop/0.1'})
    await bridge.dispatch('open', {'workspace': str(tmp_path)})
    await until(lambda: bool(bridge.pending))
    with pytest.raises(ValueError, match='BUSY'):
        await bridge.dispatch('open', {'workspace': str(tmp_path)})
    prompt = next(iter(bridge.pending))
    await bridge.dispatch('answer', {'id': prompt, 'choice': 'allow'})
    await bridge.active
    await bridge.dispatch('input', {'text': 'hello'})
    await until(lambda: bool(bridge.pending))
    prompt = next(iter(bridge.pending))
    await bridge.dispatch('answer', {'id': prompt, 'choice': 'allow_once'})
    await bridge.active
    with pytest.raises(ValueError, match='结束'):
        await bridge.dispatch('answer', {'id': prompt, 'choice': 'allow_once'})
    outputs = [m['params']['output']['text'] for m in messages if m['params']['kind'] == 'output']
    assert outputs == ['开始', '完成']
    app = bridge.application
    await asyncio.gather(bridge.shutdown(), bridge.shutdown())
    assert app.closed and bridge.stopped.is_set()


@pytest.mark.asyncio
async def test_cancel_pending_interaction_and_invalid_rpc():
    messages = []
    bridge = DesktopBridge(messages.append)
    await bridge.request({'jsonrpc': '2.0', 'id': '0', 'method': 'initialize', 'params': {'protocol': 'wrong'}})
    assert 'error' in messages[-1] and not bridge.initialized
    await bridge.dispatch('initialize', {'protocol': 'artcode-desktop/0.1'})
    bridge.application = ApplicationStub(bridge)
    await bridge.dispatch('input', {'text': 'wait'})
    await until(lambda: bool(bridge.pending))
    await bridge.dispatch('cancel', {})
    await bridge.active
    assert not bridge.pending
    assert messages[-1]['params']['busy'] is False
    await bridge.shutdown()


def test_history_projection_omits_provider_metadata_and_notices():
    fact = ToolExchangeFact((ToolRequest('id', 'read_file', '{}'),), (), ProtocolMetadata(b'secret'))
    snapshot = SessionSnapshot('test', 0, True, (fact,), pending_notices=('model only',))
    projected = public(snapshot)
    assert 'metadata' not in projected['facts'][0]
    assert 'pending_notices' not in projected
    assert projected['facts'][0]['requests'][0]['name'] == 'read_file'
