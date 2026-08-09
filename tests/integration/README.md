# ArtCode 测试说明

测试按证据类型分开，所有新增重构场景使用 `ch10_5` marker 和稳定 pytest node ID。

## 分类

- `tests/unit/`：单模块逻辑、不可变快照与状态转换。
- `tests/integration/`：Fake Provider 或真实本地组件组成的确定性跨模块链路。
- `tests/property/`：Hypothesis 生成的协议、配置、路径、权限和恢复不变量。
- `tests/fault/`：断流、取消、损坏文件、原子写失败和资源关闭故障注入。
- `tests/live/`：真实 DeepSeek、macOS Seatbelt、进程树、stdio/HTTP MCP、CLI 和多进程 Session。
- `tests/soak/`：长工具链、反复压缩、重复恢复和生命周期资源稳定性。

确定性 Agent 测试覆盖请求准备、Thinking 工具续接、Plan/Do、工具批次、权限、路径复核、上下文压缩、会话恢复、长期记忆和命令分发，不访问外部模型。真实 API 测试覆盖 Thinking 开关、usage、Prompt Cache、压缩后续聊和跨重启记忆。

## 常用命令

```bash
.venv/bin/python -m pytest -q -m "not live and not slow"
.venv/bin/python -m pytest tests/integration -q -m "not live and not slow"
.venv/bin/python -m pytest tests/property tests/fault -q -m ch10_5
.venv/bin/python -m pytest tests/live -q -m live -rs
.venv/bin/python -m pytest tests/soak -q -m soak
.venv/bin/python tests/tools/verify_test_inventory.py --baseline 413
.venv/bin/python tests/tools/verify_coverage.py
```

Inventory 脚本按独立 node ID 统计，不以测试函数数量估算，也不把原始 413 项基线重复计入新增配额。

## 真实测试规则

真实 DeepSeek 测试读取 `~/.artcode/config.yml` 或项目根目录 `artcode.yaml`。真实 CLI 测试使用隔离 HOME、临时 Workspace 和测试配置，在不发送模型请求的情况下验证 console script、`python -m artcode`、新会话和精确恢复走同一 Bootstrap。

真实测试不会因为 API 成本而跳过。缺少有效配置、macOS `sandbox-exec`、网络或外部服务时，只能报告环境阻塞或真实失败。输出和证据必须隐藏 API Key、Authorization Header、Cookie 和完整配置正文。

Seatbelt 测试验证 Workspace 写入、外部与敏感路径拒绝、子进程继承以及公网、回环、本地监听全部拒绝。MCP 测试分别覆盖真实 stdio 与 streamable HTTP 的发现、调用、取消、断开和关闭隔离。
