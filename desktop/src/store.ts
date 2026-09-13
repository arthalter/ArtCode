import { create } from 'zustand';
import { api, describe, type DesktopEvent, type Interaction, type Snapshot } from './api';
import { commandReply } from './command-results';

export interface Message { id: number; role: 'user' | 'assistant'; text: string }
interface Activity { id: number; title: string; detail: string }
interface State {
  connected: boolean; busy: boolean; closing: boolean; error: string;
  snapshot: Snapshot | null; messages: Message[]; activities: Activity[];
  interactions: Interaction[]; streaming: number | null;
  receive(event: DesktopEvent): void;
  connect(): Promise<void>;
  open(workspace: string, config: string, fresh: boolean): Promise<void>;
  send(text: string): Promise<boolean>;
  action(method: string, params?: Record<string, unknown>): Promise<void>;
  clearError(): void;
}
let nextId = 0;
let subscribed = false;
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export const useApp = create<State>((set, get) => ({
  connected: false, busy: false, closing: false, error: '', snapshot: null,
  messages: [], activities: [], interactions: [], streaming: null,
  clearError: () => set({ error: '' }),
  receive(event) {
    if (event.kind === 'busy') set({ busy: !!event.busy, ...(!event.busy ? { streaming: null } : {}) });
    if (event.kind === 'closing') set({ closing: true, busy: true });
    if (event.kind === 'disconnected') set({ connected: false, busy: false, snapshot: null, interactions: [], error: event.message || '连接已断开。' });
    if (event.kind === 'snapshot' || event.kind === 'status') {
      const snapshot = event.snapshot ?? null;
      const previous = get().snapshot;
      if (snapshot && snapshot.session.session_id !== previous?.session.session_id && snapshot.session.facts) {
        const messages: Message[] = snapshot.session.facts.flatMap((fact) => {
          const text = fact.text || fact.assistant_text;
          return text ? [{ id: ++nextId, role: fact.type === 'UserFact' ? 'user' as const : 'assistant' as const, text }] : [];
        });
        set({ messages, activities: [] });
      }
      set({ snapshot });
    }
    if (event.kind === 'interaction') {
      // The prompt category is separate from the event discriminator.
      const prompt = event as unknown as Interaction & { prompt_kind: string };
      set({ interactions: [...get().interactions.filter((item) => item.id !== prompt.id), { ...prompt, kind: prompt.prompt_kind }] });
    }
    if (event.kind === 'interaction_resolved') set({ interactions: get().interactions.filter((item) => item.id !== event.id) });
    if (event.kind !== 'output' || !event.output) return;
    const output = event.output;
    if (output.type === 'TextOutput') {
      const { streaming, messages } = get();
      if (streaming !== null) set({ messages: messages.map((item) => item.id === streaming ? { ...item, text: item.text + (output.text || '') } : item) });
      else {
        const id = ++nextId;
        set({ streaming: id, messages: [...messages, { id, role: 'assistant', text: output.text || '' }] });
      }
    } else if (output.type === 'ErrorOutput') set({ error: output.message || '执行失败。', streaming: null });
    else if (output.type === 'ClearDisplay') set({ messages: [], activities: [], streaming: null });
    else if (output.type === 'ExitRequested') set({ snapshot: null });
    else {
      const reply = commandReply(output);
      if (reply !== null) set({ messages: [...get().messages, { id: ++nextId, role: 'assistant', text: reply }] });
      const title = output.type === 'RunStopped' ? `本轮结束 · ${output.reason} · ${output.rounds} 轮` : output.name || output.type;
      set({ streaming: null, activities: [...get().activities, { id: ++nextId, title, detail: describe(output.value) }].slice(-100) });
    }
  },
  async connect() {
    if (!api) { set({ error: '请通过 ArtCode 桌面应用启动，浏览器预览不连接 Python 后端。' }); return; }
    if (!subscribed) { api.onEvent(get().receive); subscribed = true; }
    try {
      await api.request('initialize', { protocol: 'artcode-desktop/0.1' });
      const state = await api.request<{ snapshot: Snapshot | null; busy: boolean; interactions: Interaction[] }>('snapshot');
      set({ connected: true, busy: state.busy, error: '', interactions: state.interactions });
      get().receive({ kind: 'snapshot', snapshot: state.snapshot });
    } catch (error) { set({ error: errorText(error), connected: false }); }
  },
  async open(workspace, config, fresh) {
    if (!api || get().busy) return;
    set({ busy: true, error: '', streaming: null });
    try {
      if (get().snapshot) {
        await api.restart();
        set({ connected: true, snapshot: null, messages: [], activities: [], interactions: [] });
      }
      await api.request('open', { workspace, config, new: fresh });
      localStorage.setItem('artcode.workspace', workspace);
      localStorage.setItem('artcode.config', config);
    } catch (error) { set({ busy: false, error: errorText(error) }); }
  },
  async send(text) {
    if (!api || get().busy || !get().snapshot) return false;
    const id = ++nextId;
    set({ busy: true, error: '', streaming: null, messages: [...get().messages, { id, role: 'user', text }] });
    try { await api.request('input', { text }); return true; }
    catch (error) { set({ busy: false, error: errorText(error), messages: get().messages.filter((item) => item.id !== id) }); return false; }
  },
  async action(method, params = {}) {
    try { await api?.request(method, params); }
    catch (error) { set({ error: errorText(error) }); }
  },
}));
