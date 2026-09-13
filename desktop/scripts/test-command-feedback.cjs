const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { buildSync } = require('esbuild');
const folder = mkdtempSync(path.join(tmpdir(), 'artcode-command-test-'));
try {
  buildSync({ entryPoints: [path.join(__dirname, '../src/store.ts')], bundle: true,
    platform: 'node', format: 'cjs', outfile: path.join(folder, 'store.cjs') });
  global.window = { artcode: { request: async () => ({}) } };
  const { useApp } = require(path.join(folder, 'store.cjs'));
  (async () => {
    for (const [command, name, value, expected] of [
      ['/tasks', 'tasks', [], /暂无.*任务/],
      ['/skills', 'skills', { skills: [], active: [], diagnostics: [] }, /暂无.*Skill/],
      ['/sandbox', 'permission', { mode: 'default', shell_policy: 'sandbox_auto', rules: [] }, /sandbox_auto/],
      ['/worktrees', 'worktrees', [], /暂无.*Worktree/],
    ]) {
      useApp.setState({ connected: true, snapshot: {}, busy: false, messages: [], activities: [], streaming: null });
      await useApp.getState().send(command);
      useApp.getState().receive({ kind: 'output', output: { type: 'StateOutput', name, value } });
      useApp.getState().receive({ kind: 'busy', busy: false });
      const replies = useApp.getState().messages.filter(m => m.role === 'assistant');
      assert.equal(replies.length, 1, `${command} must show a reply in the conversation`);
      assert.match(replies[0].text, expected);
      assert.equal(useApp.getState().activities.length, 1, 'keep diagnostic details');
    }
    const count = useApp.getState().messages.length;
    useApp.getState().receive({ kind: 'output', output: { type: 'StateOutput', name: 'usage', value: {} } });
    assert.equal(useApp.getState().messages.length, count, 'usage must not become a chat reply');
    console.log('Command feedback: 4 commands and usage filtering passed');
  })().catch(error => { console.error(error); process.exitCode = 1; });
} finally { rmSync(folder, { recursive: true, force: true }); }
