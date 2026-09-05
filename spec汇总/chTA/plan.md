# chTA：Agent 系统效率与信息保真评测 Plan

## 实施范围

本轮只落实三条可被真实数据支持的结论：MCP 延迟加载、权限审批复用、SWE-bench-Live 修复结果与上下文信息保留。八小时会话不进入实现、报告或简历映射。

现有 ch11 evaluation 继续负责普通任务运行和基础 Trace；chTA 在其上增加实验清单、机制级事件、隔离 A/B 编排、官方评测适配和证据化报告。MCP 延迟加载本身属于生产能力，权限和版本对照只增加测量入口，不改变默认权限规则或上下文行为。

## 1. 统一实验层

### 1.1 实验清单

新增 chTA 实验清单，分别声明：

- `mcp_lazy_loading`：eager/lazy 两个 profile、百级工具 Fixture、固定任务和重复次数；
- `permission_reuse`：once/always 两个 profile、三十次正常操作和负向控制序列；
- `swebench_live`：数据集 revision、选择规则、固定 instance IDs、基线/候选提交和模型预算。

清单经过规范化和指纹计算。A/B 只有实验指纹、任务集合和公共配置一致时才允许正式比较。

### 1.2 运行目录

每个实验运行使用独立目录：

```text
artcode-eval-runs/chTA/<run-id>/
├── manifest.lock.json
├── environment.json
├── mcp/
│   ├── eager/
│   └── lazy/
├── permission/
│   ├── once/
│   └── always/
├── swebench/
│   ├── baseline/
│   ├── candidate/
│   └── gold-preflight/
├── report.json
├── report.md
└── report.xlsx
```

锁定清单只保存配置指纹和脱敏后的模型信息，不复制 API Key。

### 1.3 统一事件与证据

chTA 增加三类机器事件：

- 模型请求事件：工具定义数量、序列化字节、工具描述 Token、请求指纹；
- 权限审计事件：审批请求、审批选择、规则写入、规则命中、拒绝；
- 外部验证事件：gold preflight、补丁生成、官方测试结果、保留探针结果。

事件进入 JSONL Trace，聚合报告只从事件、usage、验证器和官方日志计算数字。

## 2. MCP 延迟加载实现与实验

### 2.1 生产能力

在保持默认 eager 行为兼容的前提下，增加 lazy 工具加载策略：

```text
MCP Server 启动并枚举工具
  -> 工具目录保存完整 Adapter 与可检索元数据
  -> 初始 Registry 只注册 MCP 检索工具
  -> 模型按查询检索
  -> 匹配工具被激活并注册到当前 Registry
  -> 下一轮请求只携带内置工具、检索工具和已激活 MCP 工具
```

检索使用确定性的名称、描述和参数字段匹配，不增加第二次 LLM 判断。激活范围绑定当前 Manager/Registry 生命周期；名称冲突、无匹配、重复激活和关闭期间激活都必须显式返回结果。

### 2.2 百级工具 Fixture

扩展本地 MCP Fixture，使其稳定暴露 120 个描述长度和参数复杂度可控的工具，其中包含一组可被任务唯一定位并产生可验证结果的目标工具。Fixture 不访问网络，不执行危险副作用。

### 2.3 A/B 任务

- eager：启动后将 120 个 MCP 工具全部注入模型请求；
- lazy：启动后只注入检索入口，按任务激活目标工具；
- 两边各运行 5 个任务，每个任务重复 3 次；
- 任务验证目标工具、参数、返回值和最终工作区结果；
- 同时比较任务成功率、首轮/累计工具描述 Token、provider prompt Token、轮次、调用次数与耗时。

工具描述 Token 使用固定的本地分词口径；provider prompt Token 使用服务端 usage，两者分列，不互相替代。

## 3. 权限审批复用实验

### 3.1 固定操作序列

实验通过真实 `ToolExecutionService -> PermissionService -> PermissionEngine -> RuleWriter` 链路回放固定工具调用，不让模型自由选择操作，以保证两边序列完全相同。

正常序列由 5 个不同的精确权限目标各重复 6 次，共 30 次副作用操作。另设不计入三十次效率分母的负向控制：

- 一个危险命令；
- 一个与已授权路径相似但不完全相同的目标；
- 一个与已授权命令共享前缀但参数不同的命令。

### 3.2 两个 profile

- once 基线：脚本化审批器对每个正常请求返回“仅本次允许”；
- always 候选：每个新精确目标首次返回“始终允许”，后续必须由权限规则自动放行；
- 负向控制不由脚本强行放行，必须在权限引擎或隔离层被拒绝。

脚本化审批器不是模拟权限结果，而是替代人工点击并记录真实审批接口被调用的次数；规则判定、写入和工具副作用全部走生产实现。

### 3.3 指标

- `approval_requests`、`allow_once`、`allow_always`；
- `rule_writes`、`rule_hits`、`denials`；
- `false_allows`、`false_denials`；
- `completed_operations`、运行耗时；
- 审批降幅：`(baseline_requests - candidate_requests) / baseline_requests`。

若固定序列与现有精确规则语义一致，预期基线请求三十次、候选首次目标请求五次；这是验收预期，不会直接写入最终报表，最终报表只读取事件实测值。

## 4. SWE-bench-Live 与历史版本对照

### 4.1 官方适配

chTA 通过独立适配器调用固定 revision 的 SWE-bench-Live 官方数据和容器验证脚本，不复制或改写官方判分逻辑。适配器负责：

- 数据集与官方仓库 revision 锁定；
- Docker、磁盘、架构、网络和依赖预检；
- gold patch 三次验证与有效任务清单落盘；
- ArtCode 补丁导出、官方验证调用和日志归档；
- 失败类型归一化，但保留原始官方日志。

### 4.2 Pilot 选择

从兼容的 Python verified 候选中按固定排序与固定种子选择任务，目标得到 6 个 gold patch 三次稳定通过的实例。环境不兼容任务只按预先声明规则剔除，并在锁定清单记录；看到 Agent 结果后不得换样本。

### 4.3 版本隔离

- baseline：`a987d15`，原始上下文管理版本；
- candidate：`92a28a7`，引入用户消息保留修复的版本；
- 当前脏工作区不参与版本运行；
- 运行器从 Git 对象创建临时只读源快照和独立 ArtCode Home，使用同一外部兼容驱动调用两个版本；
- 兼容驱动只能适配入口差异，不允许修改被测上下文算法。

### 4.4 两套结果

官方结果：

```text
resolve_rate = 官方验证通过实例数 / gold-valid 实例数
```

配套信息保留结果：从同一任务的 issue、相关文件和测试目标构造确定性探针，让两个历史版本执行同一压缩流程：

```text
retention_rate = 压缩后仍通过的探针数 / 全部探针数
```

两项结果在报告和简历映射中始终分列。若历史版本无法完成官方任务运行，仍输出构建与阻塞证据，但不伪造 resolve rate。

## 5. 汇总报告与简历映射

`report.json` 保存完整结构化数据；`report.md` 给出可审查摘要；`report.xlsx` 包含运行总览、MCP 明细、权限事件、SWE-bench 实例、信息保留探针和证据索引。

报告末尾生成“可用于简历”区块，但只在以下条件全部满足时生成数字句：

- 基线/候选可比；
- 分母大于零；
- 原始证据齐全；
- 安全负向控制全部通过；
- 数字不是 N/A、模拟值或静态单测值。

简历映射只替换数据，不自动夸大含义。例如工具描述 Token 降幅与总输入 Token 降幅分别表述；SWE-bench resolve rate 与信息保留率分别表述。

## 6. CLI

在现有 `artcode-eval` 下增加 chTA 子命令，支持：

```text
artcode-eval chTA validate <manifest>
artcode-eval chTA run <manifest> --experiment mcp
artcode-eval chTA run <manifest> --experiment permission
artcode-eval chTA run <manifest> --experiment swebench
artcode-eval chTA run <manifest> --experiment all
artcode-eval chTA report <run-dir>
```

单项失败不删除已完成产物；`all` 最终以汇总状态区分 complete、partial 和 blocked。

## 7. 测试策略

- 单元测试：清单校验、检索排序、动态激活、指标公式、报告序列化；
- 属性测试：规则不能越权匹配、工具目录顺序不改变查询结果、秘密不会落盘；
- 集成测试：真实本地 MCP Server、真实权限链路、两个历史 Git 快照；
- 故障测试：MCP Server 中断、规则写入失败、Docker 缺失、gold 失败、API 中断；
- live 测试：真实 DeepSeek MCP A/B 与 SWE-bench-Live pilot；
- 回归测试：原 CLI、MCP eager、权限、上下文和 ch11 evaluation。

## 8. 四步执行顺序

1. 建立不可变清单、事件和报告公共底座；
2. 完成 MCP lazy 生产能力及真实 A/B；
3. 完成权限固定回放及真实 A/B；
4. 接入 SWE-bench-Live、运行历史版本对照、汇总全部真实数据并填简历。
