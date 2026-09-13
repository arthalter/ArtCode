import { describe, type Output } from './api';

const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];

export function commandReply(output: Output): string | null {
  if (output.type !== 'StateOutput' || ['usage', 'tool_batch', 'isolated_skill'].includes(output.name || '')) return null;
  const value = object(output.value);
  switch (output.name) {
    case 'tasks': {
      const tasks = list(output.value);
      return tasks.length ? '子任务：\n' + tasks.map(item => {
        const task = object(item);
        return `${task.id} · ${task.state}${task.background ? ' · 后台' : ''}\n${task.task}`;
      }).join('\n\n') : '当前暂无子任务。';
    }
    case 'skills': {
      const skills = list(value.skills);
      const lines = [skills.length ? '可用 Skills：\n' + skills.map(item => {
        const skill = object(item);
        return `${skill.name} — ${skill.description}`;
      }).join('\n') : '当前暂无可用 Skill。'];
      lines.push(list(value.active).length ? `已激活：${list(value.active).join('、')}` : '当前没有激活的 Skill。');
      const diagnostics = list(value.diagnostics);
      if (diagnostics.length) lines.push('加载提示：\n' + diagnostics.map(item => {
        const diagnostic = object(item);
        return `${diagnostic.name}：${diagnostic.message}`;
      }).join('\n'));
      return lines.join('\n\n');
    }
    case 'permission':
      return `当前权限模式：${value.mode}\nShell 策略：${value.shell_policy}\n已保存授权规则：${list(value.rules).length} 条`;
    case 'worktrees':
      return list(output.value).length ? `Worktree 成果：\n${describe(output.value)}` : '当前暂无 Worktree 成果。';
    default:
      return `命令结果（${output.name || '状态'}）：\n${describe(output.value)}`;
  }
}
