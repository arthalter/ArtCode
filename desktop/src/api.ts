export type ObjectValue = Record<string, unknown>;
export interface Fact { type: string; text?: string; assistant_text?: string }
export interface Task { id: string; task: string; state: string; background: boolean; result: string }
export interface Snapshot {
  workspace: string; running: boolean; closed: boolean; tasks: Task[];
  session: { session_id: string; facts?: Fact[]; restored: boolean; latest_plan: string | null };
  permission: { mode?: string; shell_policy?: string };
}
export interface Interaction { id: string; kind: string; value: unknown; choices: string[] }
export interface Output { type: string; text?: string; message?: string; name?: string; value?: unknown; reason?: string; rounds?: number }
export interface DesktopEvent {
  kind: string; output?: Output; snapshot?: Snapshot | null; busy?: boolean;
  id?: string; value?: unknown; choices?: string[]; message?: string;
}
export interface DesktopAPI {
  request<T = unknown>(method: string, params?: ObjectValue): Promise<T>;
  choose(kind: 'workspace' | 'config'): Promise<string | null>;
  restart(): Promise<unknown>;
  onEvent(listener: (event: DesktopEvent) => void): () => void;
}
declare global { interface Window { artcode?: DesktopAPI } }
export const api = window.artcode;
export const describe = (value: unknown): string => typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? '';
