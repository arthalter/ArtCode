import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, describe } from './api';
import { useApp } from './store';
import styles from './style.module.css';

function ProjectPanel() {
  const { connected, busy, snapshot, open, connect } = useApp();
  const [workspace, setWorkspace] = useState(localStorage.getItem('artcode.workspace') || '');
  const [config, setConfig] = useState(localStorage.getItem('artcode.config') || '');
  const [fresh, setFresh] = useState(false);
  const choose = async (kind: 'workspace' | 'config') => {
    const result = await api?.choose(kind);
    if (result) (kind === 'workspace' ? setWorkspace : setConfig)(result);
  };
  return <section className={styles.project}>
    <div className={styles.eyebrow}>WORKSPACE</div>
    <label>项目目录<input aria-label="项目目录" value={workspace} onChange={e => setWorkspace(e.target.value)} placeholder="选择你要工作的文件夹" disabled={busy} /></label>
    <button disabled={busy || !api} onClick={() => void choose('workspace')}>选择文件夹</button>
    <details><summary>模型配置与会话</summary>
      <label>配置文件<input aria-label="配置文件" value={config} onChange={e => setConfig(e.target.value)} placeholder="默认使用 ~/.artcode/config.yml" disabled={busy} /></label>
      <button disabled={busy || !api} onClick={() => void choose('config')}>选择配置文件</button>
      <label className={styles.check}><input type="checkbox" checked={fresh} onChange={e => setFresh(e.target.checked)} disabled={busy} />新建会话（默认恢复最近会话）</label>
    </details>
    {connected ? <button className={styles.primary} disabled={!workspace.trim() || busy} onClick={() => {
      if (snapshot && !confirm('重新打开项目会结束当前后台任务。已保存会话和文件会保留。')) return;
      void open(workspace.trim(), config.trim(), fresh);
    }}>{snapshot ? '重新打开项目' : busy ? '正在打开…' : '打开项目'}</button>
      : <button className={styles.primary} onClick={() => void connect()}>连接后端</button>}
    {snapshot && <div className={styles.session}><span>当前会话</span><code>{snapshot.session.session_id}</code><small>{snapshot.session.restored ? '已恢复历史' : '新会话'} · 仅保存在本机</small></div>}
  </section>;
}

function Approvals() {
  const { interactions, action } = useApp();
  const [answering, setAnswering] = useState<string | null>(null);
  const labels: Record<string, string> = { allow_once: '本次允许', deny_once: '本次拒绝', allow_always: '以后允许', deny_always: '以后拒绝', allow: '允许启动', deny: '拒绝', discard: '确认丢弃', keep: '保留', wait: '等待完成', cancel: '取消并退出', return: '返回' };
  const titles: Record<string, string> = { tool: '工具请求授权', mcp: '启动项目 MCP 服务', discard: '丢弃 Worktree 成果', exit: '后台任务仍在运行' };
  return <>{interactions.map(item => <section className={styles.approval} key={item.id}>
    <div className={styles.eyebrow}>需要你的决定</div><h3>{titles[item.kind] || '确认操作'}</h3>
    <pre>{describe(item.value)}</pre><div className={styles.buttons}>{item.choices.map(choice => <button key={choice} disabled={answering === item.id} onClick={async () => {
      setAnswering(item.id); await action('answer', { id: item.id, choice }); setAnswering(null);
    }}>{labels[choice] || choice}</button>)}</div>
  </section>)}</>;
}

function Conversation() {
  const { messages, busy, snapshot } = useApp();
  const bottom = useRef<HTMLDivElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useEffect(() => { if (follow.current) bottom.current?.scrollIntoView({ block: 'end' }); }, [messages, busy]);
  return <div ref={scroll} className={styles.conversation} onScroll={() => {
    const el = scroll.current; if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
  }}>
    {!messages.length && <div className={styles.welcome}><div className={styles.mark}>A</div><h1>把想法，变成代码。</h1><p>{snapshot ? '描述你想完成的事情。ArtCode 会在当前项目中工作。' : '打开一个本地项目，继续你的工作。'}</p><div className={styles.tags}><span>本地工作区</span><span>可控执行</span><span>连续会话</span></div></div>}
    {messages.map(message => <article key={message.id} className={`${styles.message} ${message.role === 'user' ? styles.user : ''}`}>
      <div className={styles.author}>{message.role === 'user' ? '你' : 'ARTCODE'}</div><div className={styles.messageText}>{message.text}</div>
    </article>)}
    {busy && <div className={styles.working}><span className={styles.dot} />正在处理，可随时取消</div>}
    <Approvals /><div ref={bottom} />
  </div>;
}

function Composer() {
  const { busy, snapshot, connected, send, action } = useApp();
  const [text, setText] = useState('');
  const [mode, setMode] = useState('chat');
  const submit = async () => {
    if (!text.trim() && mode !== 'act') return;
    const goal = mode === 'plan' ? `/plan ${text}` : mode === 'act' ? `/act ${text}` : text;
    if (await send(goal)) setText('');
  };
  return <div className={styles.composer}>
    <textarea aria-label="任务内容" value={text} onChange={e => setText(e.target.value)} disabled={!snapshot || !connected} placeholder="描述任务，或输入 /help 查看现有命令…" onKeyDown={e => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing && !busy) { e.preventDefault(); void submit(); }
    }} />
    <div className={styles.composeActions}><select aria-label="执行模式" value={mode} onChange={e => setMode(e.target.value)} disabled={busy}>
      <option value="chat">普通任务</option><option value="plan">制定计划</option><option value="act">执行最近计划</option>
    </select><span>⌘ Enter 发送</span>{busy ? <button className={styles.cancel} onClick={() => void action('cancel')}>取消执行</button> : <button className={styles.primary} disabled={!snapshot || !connected || (!text.trim() && mode !== 'act')} onClick={() => void submit()}>发送 ↗</button>}</div>
  </div>;
}

function ActivityPanel() {
  const { activities, snapshot, busy, send, action } = useApp();
  return <aside className={styles.activity}>
    <div className={styles.eyebrow}>执行记录</div><h3>活动与任务</h3><p className={styles.hint}>工具结果在执行完成后显示，后台任务状态持续更新。</p>
    {snapshot?.tasks.map(task => <details key={task.id} className={styles.task}><summary>{task.state} · {task.task.slice(0, 40)}</summary><p>{task.task}</p><small>{task.id} · {task.background ? '后台' : '前台'}</small><pre>{task.result}</pre>
      {!busy && ['queued', 'running'].includes(task.state) && <button onClick={() => void send(`/task-cancel ${task.id}`)}>取消该任务</button>}
    </details>)}
    {busy && <button onClick={() => void action('background')}>将前台子任务转入后台</button>}
    {!activities.length && !snapshot?.tasks.length && <div className={styles.empty}>执行记录会出现在这里。</div>}
    {activities.slice().reverse().map(item => <details className={styles.task} key={item.id}><summary>{item.title}</summary>{item.detail && <pre>{item.detail}</pre>}</details>)}
  </aside>;
}

function App() {
  const { connected, busy, closing, error, clearError, snapshot, send, connect } = useApp();
  useEffect(() => { void connect(); }, [connect]);
  return <div className={styles.app}>
    <aside className={styles.sidebar}><div className={styles.brand}><span>A</span> ArtCode <small>LOCAL</small></div><ProjectPanel />
      <div className={styles.shortcuts}><div className={styles.eyebrow}>工作区工具</div>{[['/skills', 'Skills'], ['/tasks', '子任务'], ['/worktrees', 'Worktrees'], ['/permissions', '权限设置'], ['/sandbox', '沙箱状态'], ['/help', '全部命令']].map(([command, label]) => <button key={command} disabled={!snapshot || busy} onClick={() => void send(command)}>{label}<span>↗</span></button>)}</div>
      <div className={styles.sidebarFooter}>你的项目，你的执行环境。<br />ArtCode Desktop · 0.1</div>
    </aside>
    <main className={styles.main}><header className={styles.header}><div><strong>{snapshot?.workspace.split('/').filter(Boolean).pop() || '开始工作'}</strong><small>{snapshot?.workspace || '选择项目以开始会话'}</small></div><span className={styles.badge}>{closing ? '正在清理并退出' : busy ? '执行中' : connected ? '已连接' : '未连接'}</span></header>
      {error && <div role="alert" className={styles.error}><span>{error}</span><button onClick={clearError}>关闭</button></div>}
      <Conversation /><Composer />
    </main><ActivityPanel />
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
