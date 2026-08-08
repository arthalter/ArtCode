# ch06：权限系统 Checklist

> 每一项都必须通过运行命令、测试或观察终端行为验证。只有真实 macOS Seatbelt 测试、完整测试套件和端到端场景全部通过，ch06 才能标记完成。

> 验收记录（2026-07-26）：已运行完整测试套件（223 passed）、真实 DeepSeek、真实 Prompt Cache、真实 macOS Seatbelt、CLI 冷启动、wheel 安装与资源定位、`compileall` 和 `git diff --check`。
> `[x]` 表示本轮已有自动测试或实际观察证据；`[ ]` 表示明确未满足或仍缺少该条要求的专项端到端证据。


## 验收前提

- [x] 验收机器运行 macOS，且 `/usr/bin/sandbox-exec` 实际存在。（验证：运行 `test -x /usr/bin/sandbox-exec`，期望退出码为 0）
- [x] `~/.artcode/config.yml` 存在有效的真实 API 配置。（验证：启动 ArtCode，期望配置加载成功且终端只显示脱敏 API Key）
- [x] 真实测试使用独立临时 Workspace，不直接破坏 ArtCode 源码或用户项目。（验证：检查测试输出中的 Workspace 路径位于 pytest 临时目录）
- [x] 内置危险命令测试不真正执行危险命令。（验证：检查测试使用 prepare/validator 路径并断言执行器未启动）

## ArtCode Home 与主配置

- [x] `~/.artcode/` 不存在时首次启动会自动创建。（验证：使用临时 HOME 启动，观察目录创建成功）
- [x] `~/.artcode/skills/` 不存在时首次启动会自动创建。（验证：使用临时 HOME 启动，观察目录创建成功）
- [x] 主配置只从 `~/.artcode/config.yml` 读取。（验证：分别在 Home 和 Workspace 放置不同模型配置，启动后观察使用 Home 配置）
- [x] Workspace 中存在旧 `artcode.yaml` 时不会读取、迁移或报专门的兼容错误。（验证：只在 Workspace 放置旧文件，观察程序仍按 Home 配置行为处理）
- [x] `config.example.yml` 指引用户复制到 `~/.artcode/config.yml`。（验证：打开示例文件，观察说明和字段完整）
- [x] 配置模型中不存在 `ToolConfig` 和 `tools.allowed_dirs`。（验证：运行配置单元测试并检查安全状态不再包含 allowed_dirs）
- [x] 项目中不存在写死的 `/Users/arthalter/Work/ArtCode/实验场` 安全默认值。（验证：运行 `rg 'DEFAULT_ALLOWED_DIR|Work/ArtCode/实验场' artcode tests`，期望实现代码无匹配）
- [x] API Key、Token、密码不会以完整文本出现在启动状态或错误中。（验证：使用已知测试秘密触发启动错误，观察输出只含脱敏文本）

## Workspace

- [x] 不带 `--workspace` 启动时，启动命令所在目录成为 Workspace。（验证：从临时目录启动并查看启动状态）
- [x] `artcode --workspace <已有目录>` 使用指定目录作为 Workspace。（验证：从目录 A 指向目录 B 启动，观察 Workspace 为 B）
- [x] `--workspace` 接受相对路径并转换为规范真实绝对路径。（验证：使用相对参数启动，观察状态显示真实路径）
- [x] `--workspace` 指向不存在路径时启动失败且不创建目录。（验证：传入不存在路径，观察失败后路径仍不存在）
- [x] `--workspace` 指向普通文件时启动失败。（验证：传入临时文件，观察友好启动错误）
- [x] Workspace 根目录本身是符号链接时保存其真实目标作为边界。（验证：通过指向临时项目的符号链接启动，观察状态显示规范路径）
- [x] 运行期间不存在 `/workspace` 切换命令。（验证：查看 `/help` 并输入 `/workspace`，观察 Workspace 不改变）
- [x] 相对文件路径以 Workspace 为基准解析。（验证：从其他应用目录启动并读取 Workspace 中的相对文件）
- [x] `run_command` 未提供 cwd 时在 Workspace 根目录执行。（验证：运行 `pwd`，观察输出为 Workspace）
- [x] `run_command` 指定 Workspace 内子目录时在该目录执行。（验证：在子目录运行 `pwd`，观察输出正确）
- [x] `run_command` 指定 Workspace 外 cwd 时在启动进程前拒绝。（验证：请求外部 cwd，观察结构化越界错误且命令无副作用）

## Plan 独立限制

- [x] Plan 仍是独立 Agent 运行状态，不出现在 Default/Edit/Full 权限模式枚举中。（验证：运行模式单元测试）
- [x] Plan 请求中只向模型暴露 `read_file`、`find_files`、`search_text`。（验证：检查 Fake Provider 收到的 tools）
- [x] Plan 中 `write_file` 请求直接 DENY，不进入规则或 HITL。（验证：构造异常 Tool Call，观察审批器未调用）
- [x] Plan 中 `edit_file` 请求直接 DENY，不进入规则或 HITL。（验证：构造异常 Tool Call，观察文件未修改）
- [x] Plan 中 `run_command` 请求直接 DENY，不启动 zsh 或 Seatbelt。（验证：注入命令启动 Spy，观察未调用）
- [x] Plan 的写操作不能被三层 ALLOW 规则解除。（验证：写入精确 ALLOW 后重复测试，结果仍为 DENY）
- [x] Plan 的只读工具仍执行 Workspace 路径检查。（验证：请求读取 Workspace 外文件，观察拒绝）
- [x] Plan 正常生成的计划仍保存到 Plan Memory。（验证：运行现有 Plan 单元与集成测试）
- [x] `/do` 仍执行最近计划，并使用当前权限模式与 Shell 策略。（验证：Plan 后切换模式再 `/do`，观察最新权限生效）

## 三种权限模式

- [x] 每次启动时权限模式为 Default。（验证：查看启动状态和 `/permission` 输出）
- [x] Default 下 `read_file`、`find_files`、`search_text` 在 NO_MATCH 时为 ALLOW。（验证：参数化权限引擎测试）
- [x] Default 下 `write_file`、`edit_file` 在 NO_MATCH 时为 ASK。（验证：参数化权限引擎测试）
- [x] Edit 下五个文件工具在 NO_MATCH 时均为 ALLOW。（验证：执行 `/permission edit` 后逐个检查）
- [x] Full 下五个文件工具在 NO_MATCH 时均为 ALLOW。（验证：执行 `/permission full` 后逐个检查）
- [x] Default、Edit、Full 本身不产生 DENY。（验证：检查模式矩阵只包含 ALLOW 与 ASK）
- [x] `/permission default` 切换为 Default。（验证：执行命令后查询当前状态）
- [x] `/permission edit` 切换为 Edit。（验证：执行命令后查询当前状态）
- [x] `/permission full` 切换为 Full。（验证：执行命令后查询当前状态）
- [x] `/permission` 不带参数时只显示当前模式、说明和可选值。（验证：执行后观察状态未改变）
- [x] `/permission` 使用非法参数时不改变当前模式。（验证：先切 Edit，再执行非法值，查询仍为 Edit）
- [x] 权限模式不写入 `~/.artcode/config.yml` 或权限文件。（验证：切换前后比较文件内容哈希）
- [x] 退出并重启后权限模式恢复 Default。（验证：切换 Full、退出、重启并查询）

## 三种 Shell 策略

- [x] 每次启动时 Shell 策略为 Sandbox Auto。（验证：查看启动状态和 `/sandbox` 输出）
- [x] Sandbox Auto 在规则 NO_MATCH 时让命令直接进入 Seatbelt。（验证：执行普通 `pwd`，观察无 HITL 且命令调用包含 `sandbox-exec`）
- [x] Sandbox Ask 在规则 NO_MATCH 时弹出 HITL。（验证：切换 `/sandbox ask` 后执行普通命令）
- [x] Sandbox Ask 获得允许后仍通过 Seatbelt 执行。（验证：审批仅本次允许，检查命令形状包含 Profile）
- [x] Unsandboxed Ask 在规则 NO_MATCH 时弹出 HITL。（验证：确认 `/sandbox off` 后执行普通命令）
- [x] Unsandboxed Ask 获得允许后直接启动固定 zsh，不调用 `sandbox-exec`。（验证：检查命令启动参数）
- [x] `/sandbox auto` 切换为 Sandbox Auto。（验证：执行后查询状态）
- [x] `/sandbox ask` 切换为 Sandbox Ask。（验证：执行后查询状态）
- [x] `/sandbox off` 先显示失去 Seatbelt 的风险并要求确认。（验证：观察确认提示）
- [x] 用户拒绝 `/sandbox off` 风险确认时保持原 Shell 策略。（验证：从 Auto 拒绝切换后查询仍为 Auto）
- [x] `/sandbox` 不带参数时只显示当前策略、说明和可选值。（验证：执行前后比较状态）
- [x] Shell 策略不跨会话保存。（验证：切换 Off、退出、重启后观察恢复 Auto）
- [x] 不存在“Seatbelt 关闭且 NO_MATCH 自动执行”的状态。（验证：遍历 Shell 策略枚举和默认矩阵）

## 路径沙箱

- [x] `read_file` 可以读取 Workspace 内普通 UTF-8 文件。（验证：读取临时文件并比较内容）
- [x] `write_file` 可以按权限决策写入 Workspace 内普通文件。（验证：批准后比较文件内容）
- [x] `edit_file` 可以按权限决策修改 Workspace 内普通文件。（验证：批准后比较唯一替换结果）
- [x] `find_files` 只返回 Workspace 内普通文件。（验证：在内外创建匹配文件，观察只返回内部）
- [x] `search_text` 只返回 Workspace 内普通文件的匹配。（验证：在内外写相同文本，观察只返回内部）
- [x] Workspace 外绝对路径在读取前拒绝。（验证：使用读取 Spy 或权限测试确认目标未打开）
- [x] Workspace 外绝对路径在写入前拒绝。（验证：目标文件不存在或内容不变）
- [x] `../` 解析后越出 Workspace 时拒绝。（验证：覆盖读、写、编辑三类测试）
- [x] 新文件的真实父目录位于 Workspace 外时拒绝。（验证：通过符号链接父目录尝试创建）
- [x] Workspace 内符号链接指向外部文件时拒绝读取和修改。（验证：真实外部目标内容不变）
- [x] Workspace 内符号链接指向内部文件时允许按真实目标访问。（验证：读取与编辑内部目标）
- [x] `find_files` 不通过目录符号链接返回 Workspace 外文件。（验证：创建外部目录链接并执行递归 Glob）
- [x] `search_text` 不通过目录符号链接搜索 Workspace 外内容。（验证：外部命中特征文本不出现在结果）
- [x] 路径包含与 Workspace 相似的字符串前缀但不是子路径时拒绝。（验证：比较 `/project` 与 `/project-other`）

## 敏感路径

- [x] `~/.artcode/config.yml` 对文件工具和沙箱 Shell 均不可读取、不可写入。（验证：分别尝试 read、write、cat、重定向）
- [x] `~/.artcode/permissions.yml` 对模型工具不可读取、不可写入。（验证：文件工具和 Shell 尝试均失败）
- [x] `<workspace>/.artcode/permissions.yml` 对模型工具不可读取、不可写入。（验证：文件工具和 Shell 尝试均失败）
- [x] `<workspace>/permissions.local.yml` 对模型工具不可读取、不可写入。（验证：文件工具和 Shell 尝试均失败）
- [x] `~/.artcode/skills/` 整个目录对模型工具不可读取、不可写入。（验证：目录中放置探针文件并尝试访问）
- [x] 内置危险命令 YAML 对沙箱 Shell 不可读取、不可写入。（验证：在真实 Profile 下尝试读取与覆盖）
- [x] 内置 Seatbelt 模板对沙箱 Shell 不可读取、不可写入。（验证：在真实 Profile 下尝试读取与覆盖）
- [x] 生成后的 Seatbelt Profile 对沙箱 Shell 不可读取、不可写入。（验证：将 Profile 路径传入测试命令，观察拒绝）
- [x] ALLOW 规则不能解除敏感路径拒绝。（验证：写入精确 ALLOW 后重复访问）
- [x] Full 模式不能解除敏感路径拒绝。（验证：切换 Full 后重复访问）
- [x] HITL 不会为已被敏感路径层拒绝的调用弹窗。（验证：注入审批 Spy，观察未调用）
- [x] 可信配置加载器仍可读取主配置。（验证：ArtCode 正常启动）
- [x] 可信规则加载器仍可读取三层权限文件。（验证：合法规则能够影响工具决策）
- [x] 可信 RuleWriter 能更新本地权限文件。（验证：HITL“都允许”后观察规则写入）

## 危险命令

- [x] 内置危险命令 YAML 每条规则都包含稳定 ID、正则和原因。（验证：运行规则 schema 测试）
- [x] 内置危险命令 YAML 或正则非法时启动失败。（验证：向测试加载器提供损坏资源）
- [x] 递归删除系统根目录的基准形式被 DENY。（验证：参数化 validator 测试）
- [x] `mkfs` 与相关磁盘格式化命令被 DENY。（验证：参数化 validator 测试）
- [x] `dd` 直接写磁盘设备被 DENY。（验证：参数化 validator 测试）
- [x] 根目录递归 `chmod 777` 被 DENY。（验证：参数化 validator 测试）
- [x] fork bomb 基准形式被 DENY。（验证：参数化 validator 测试）
- [x] `curl` 或 `wget` 管道执行 sh、bash、zsh、ksh 的基准形式被 DENY。（验证：参数化 validator 测试）
- [x] macOS `diskutil` 擦除、分区或清除命令被 DENY。（验证：参数化 validator 测试）
- [x] macOS `newfs_*` 格式化命令被 DENY。（验证：参数化 validator 测试）
- [x] 写入 `/dev/disk*` 和 `/dev/rdisk*` 的基准形式被 DENY。（验证：参数化 validator 测试）
- [x] 删除当前 Workspace 根目录的基准形式被动态 DENY。（验证：使用包含空格的临时 Workspace 测试）
- [x] 约定的 `git reset --hard`、`git clean -f*` 和整体 restore/checkout 被 DENY。（验证：参数化 validator 测试）
- [x] 普通 `ls`、`git status`、读取和测试命令不会被危险正则误拒绝。（验证：负例参数化测试）
- [x] 危险命令命中后不读取权限规则、不进入模式兜底、不调用 HITL、不启动进程。（验证：为四个后续组件注入 Spy）
- [x] 危险命令的结构化结果包含命中规则 ID 和拒绝原因。（验证：解析 `ToolResult.to_model_content()`）

## 规则文件与格式

- [x] 用户级规则固定读取 `~/.artcode/permissions.yml`。（验证：只在该文件写规则并观察命中）
- [x] 项目级规则固定读取 `<workspace>/.artcode/permissions.yml`。（验证：只在该文件写规则并观察命中）
- [x] 本地级规则固定读取 `<workspace>/permissions.local.yml`。（验证：只在该文件写规则并观察命中）
- [x] 三个文件均不存在时规则结果为 NO_MATCH，ArtCode 正常运行。（验证：空 Home 与空 Workspace 测试）
- [x] 已存在但为空的规则文件按约定的合法空结构处理。（验证：加载空规则文档，观察无匹配）
- [x] YAML 语法错误能指出具体文件并停止当前操作。（验证：逐层放置非法 YAML）
- [x] YAML 顶层结构错误能指出具体文件并停止当前操作。（验证：使用列表或字符串作为顶层）
- [x] 缺少 `rules` 或规则字段错误时行为符合规则 schema。（验证：参数化非法结构测试）
- [x] 未知工具名称导致规则文件错误。（验证：使用 `unknown_tool(*)`）
- [x] action 不是 `allow`、`ask`、`deny` 时导致规则文件错误。（验证：使用非法 action）
- [x] `工具名(pattern)` 缺少左括号或末尾右括号时导致规则文件错误。（验证：参数化表达式测试）
- [x] 工具名为空或 pattern 为空时导致规则文件错误。（验证：参数化表达式测试）
- [x] pattern 内部包含括号时仍能正确解析。（验证：匹配 `python -c "print('hello')"`）
- [x] 规则文件错误时不使用上一次有效快照。（验证：先加载 ALLOW，再破坏文件并重复调用）
- [x] 规则文件错误时不退回权限模式。（验证：Full 模式下损坏文件，观察操作仍停止）
- [x] 规则文件错误时不进入 HITL。（验证：注入审批 Spy，观察未调用）
- [x] 修复规则文件后下一次工具调用自动使用新内容。（验证：无需重启完成错误—修复—成功流程）

## Glob 与匹配目标

- [x] 文件 pattern 匹配 Workspace 相对路径，不匹配机器绝对路径。（验证：移动临时 Workspace 后相同规则仍命中）
- [x] 文件路径匹配统一使用 `/`。（验证：规范路径测试）
- [x] `*` 不跨越 `/`。（验证：`src/*.py` 不匹配 `src/a/b.py`）
- [x] `**` 可以跨越任意目录层级。（验证：`src/**/*.py` 匹配多层文件）
- [x] `?` 只匹配一个普通字符。（验证：正例与双字符反例）
- [x] 字符集合能够匹配指定字符。（验证：`file[12].py` 正反例）
- [x] 路径 Glob 区分大小写。（验证：`src/**` 不匹配 `Src/file.py`）
- [x] 命令 Glob 区分大小写。（验证：`git status*` 不匹配 `GIT STATUS`）
- [x] 命令匹配前去除首尾空格、Tab 和换行。（验证：带首尾空白的命令命中相同规则）
- [x] 命令内部多个空格和换行保持原样。（验证：内部空白不同的规则不误命中）
- [x] `run_command(git status*)` 能匹配 `git status --short`。（验证：规则 matcher 单元测试）
- [x] `run_command(git status)` 不匹配 `git status --short`。（验证：规则 matcher 单元测试）
- [x] `read_file`、`write_file`、`edit_file` 匹配规范目标文件。（验证：逐工具参数化测试）
- [x] `find_files` 和 `search_text` 匹配实际扫描起始路径。（验证：不同扫描根使用不同规则）
- [x] `run_command` 匹配去除首尾空白后的完整命令文本。（验证：复合命令与精确规则测试）

## 三层规则合并

- [x] 每个层级只采用最后一条匹配规则作为该层有效结果。（验证：同层 ALLOW、ASK、DENY 排列组合测试）
- [x] 用户级有效 DENY 不能被项目级或本地级 ALLOW 覆盖。（验证：三层冲突测试）
- [x] 项目级有效 DENY 不能被本地级 ALLOW 覆盖。（验证：三层冲突测试）
- [x] 本地级有效 DENY 直接得到 DENY。（验证：三层冲突测试）
- [x] 同层较早 DENY 被同层较晚 ALLOW 覆盖后不再属于有效 DENY。（验证：同层顺序测试）
- [x] 没有有效 DENY 时，本地级 ALLOW/ASK 覆盖项目级与用户级。（验证：参数化冲突测试）
- [x] 本地级 NO_MATCH 时，项目级 ALLOW/ASK 覆盖用户级。（验证：参数化冲突测试）
- [x] 三层全部 NO_MATCH 时返回 NO_MATCH。（验证：空规则测试）
- [x] 规则 ALLOW 能将 Default 的文件 ASK 放宽为 ALLOW。（验证：精确 write_file ALLOW）
- [x] 规则 ASK 能将 Edit 或 Full 的文件 ALLOW 收紧为 ASK。（验证：精确 edit_file ASK）
- [x] 规则 DENY 能拒绝任何权限模式和 Shell 策略下的操作。（验证：遍历模式与策略）
- [x] 规则 NO_MATCH 时文件工具使用当前权限模式。（验证：遍历 Default/Edit/Full）
- [x] 规则 NO_MATCH 时命令使用当前 Shell 策略，不使用文件权限模式。（验证：遍历三种 Shell 策略）

## HITL

- [x] ASK 时目标工具尚未执行。（验证：审批前检查探针文件或进程 Spy）
- [x] ASK 时后续工具和下一轮模型请求尚未启动。（验证：事件顺序测试）
- [x] 审批界面展示工具名称、规范目标或完整命令。（验证：捕获 Rich 输出）
- [x] 审批界面展示 Workspace、当前权限模式和 Shell 策略。（验证：捕获 Rich 输出）
- [x] 审批界面说明 ASK 来自哪一层规则或哪种兜底模式。（验证：分别构造规则 ASK 与 NO_MATCH）
- [x] “仅本次允许”执行当前工具且不修改任何权限文件。（验证：前后比较三层文件）
- [x] “仅本次禁止”拒绝当前工具且不修改任何权限文件。（验证：前后比较三层文件）
- [x] “都允许”先将精确 ALLOW 写入本地级，再执行当前工具。（验证：检查事件和文件写入顺序）
- [x] “都禁止”将精确 DENY 写入本地级，并拒绝当前工具。（验证：检查文件和工具 Spy）
- [x] 长期文件规则只包含当前 Workspace 相对目标，不自动改成父目录 `/**`。（验证：查看写入 YAML）
- [x] 长期命令规则只包含当前完整命令，不自动添加 `*`。（验证：查看写入 YAML）
- [x] 本地级已有相同 match 时更新 action、移到末尾且只保留一项。（验证：准备重复规则后执行长期决定）
- [x] 不同 match 的既有规则顺序保持不变。（验证：比较写回前后规则序列）
- [x] 写回后的 YAML 能被重新加载并产生预期决策。（验证：RuleWriter 后立即调用 RuleLoader）
- [x] 注释、空行和引号允许被重新格式化，不作为失败条件。（验证：带注释输入后只比较语义）
- [x] 本地规则无法读取、解析、校验、写入或原子替换时停止当前工具。（验证：参数化文件错误测试）
- [x] HITL 中 `Ctrl+C` 取消整个 Agent Loop。（验证：异步取消测试）
- [x] HITL 取消后不写规则、不执行当前工具、不处理后续工具。（验证：三个 Spy 均未调用）
- [x] 同轮多个 ASK 按模型原始顺序逐个出现，不并发弹窗。（验证：记录审批调用时间与顺序）
- [x] 一个工具仅本次禁止后，后续工具仍继续权限判断。（验证：多工具集成测试）
- [x] 最终 ToolResult 按模型原始调用顺序写回上下文。（验证：检查 Conversation Context）

## Seatbelt 启动与生命周期

- [x] 启动时检测 `/usr/bin/sandbox-exec`。（验证：注入不存在路径，观察启动失败）
- [x] 不存在 `sandbox-exec` 时不自动进入 Unsandboxed Ask。（验证：检查状态和命令启动 Spy）
- [x] 每次启动创建独立专用临时目录。（验证：两次初始化路径不同）
- [x] 专用临时目录通过 Shell 的 `TMPDIR` 暴露。（验证：沙箱中运行 `printf %s \"$TMPDIR\"`）
- [x] 内置模板安全填入包含空格和特殊字符的 Workspace 路径。（验证：使用特殊路径生成并自检）
- [x] Profile 启动时只生成一次，多个命令复用同一路径。（验证：记录生成器调用次数）
- [x] 启动时使用 Profile 运行 `/usr/bin/true` 成功。（验证：真实最小自检）
- [x] Profile 语法错误时 ArtCode 启动失败。（验证：使用损坏模板）
- [x] 自检失败显示简短原因和 Profile 路径，不打印完整策略。（验证：捕获终端输出）
- [x] 退出时尽量清理 Profile 和专用临时目录。（验证：正常退出后检查路径不存在）
- [x] 运行期间 Profile 丢失或损坏时当前命令失败且不降级。（验证：启动后删除或改坏 Profile）

## Seatbelt 真实强制边界

- [x] 沙箱命令可以读取普通系统文件。（验证：真实读取非敏感系统探针并观察成功）
- [x] 沙箱命令可以读取 Workspace 普通文件。（验证：真实 `cat` Workspace 探针）
- [x] 沙箱命令不能读取任一敏感文件或敏感目录内容。（验证：逐项真实命令，期望非零退出）
- [x] 沙箱命令可以在 Workspace 创建普通文件。（验证：真实重定向并检查内容）
- [x] 沙箱命令可以在专用临时目录创建文件。（验证：真实写入 `$TMPDIR`）
- [x] 沙箱命令不能在 Workspace 外普通目录创建或修改文件。（验证：真实外部临时目标内容不变）
- [x] 沙箱命令不能修改三层权限文件。（验证：真实重定向和子进程写入均失败）
- [x] 沙箱命令不能修改 Skills、危险命令规则、模板或 Profile。（验证：逐项比较文件哈希）
- [x] 沙箱命令不能访问公网。（验证：向稳定外部地址发起带短超时请求，期望被策略拒绝）
- [x] 沙箱命令不能访问局域网目标。（验证：对测试局域网地址发起连接，期望被策略拒绝）
- [x] 沙箱命令不能访问 `localhost`、`127.0.0.1` 或 `::1` 测试服务。（验证：启动本地服务后连接失败）
- [x] zsh 启动的 Python、Git 或其他子进程继承文件写入限制。（验证：子进程尝试外部写入失败）
- [x] zsh 启动的子进程继承网络限制。（验证：子进程尝试回环或外部连接失败）
- [x] 规则 ALLOW、Sandbox Auto 和 HITL 允许都不会去掉 `sandbox-exec` 包装。（验证：三条路径分别检查启动参数）

## Shell 执行与环境

- [x] `run_command` 使用 `/bin/zsh -f -c`，不使用默认 `create_subprocess_shell`。（验证：检查进程创建 Spy）
- [x] zsh 不主动加载用户个人 rc 文件。（验证：在临时 HOME 放置产生探针的 `.zshrc`，观察探针不存在）
- [x] Shell 环境只包含约定的安全变量白名单。（验证：运行 `env` 并比较键集合）
- [x] Shell 环境不包含名称或值对应 API Key、Token、Secret、Password、Credential 的变量。（验证：向主进程注入测试秘密后运行 `env`）
- [x] Shell 输出不包含 `~/.artcode/config.yml` 中的 API Key。（验证：尝试读取被拒绝并扫描工具结果）
- [x] 命令正常退出时返回真实退出码、stdout 和 stderr。（验证：分别产生三种输出）
- [x] 非零退出码返回结构化 `command_failed`，Agent Loop 可以继续。（验证：Fake Provider 失败修正流程）
- [x] 命令运行超过 10 秒时返回结构化超时错误。（验证：运行长等待命令）
- [x] 超时后 Shell 与整个子进程组均已终止。（验证：子进程持续写探针，超时后文件不再增长）
- [x] 单次命令结果超过 20KB 时截断并标记 truncated。（验证：生成大输出并检查字节数）
- [x] Seatbelt 启动失败时返回结构化沙箱错误，不执行无沙箱 zsh。（验证：进程启动 Spy）

## TUI 与动态提醒

- [x] 启动面板展示规范 Workspace 路径。（验证：捕获启动渲染）
- [x] 启动面板展示 Default/Edit/Full 当前值。（验证：捕获启动渲染）
- [x] 启动面板展示 Sandbox Auto/Ask/Off 当前值。（验证：捕获启动渲染）
- [x] 启动面板展示 Seatbelt 自检成功状态。（验证：捕获启动渲染）
- [x] `/help` 包含 `/permission` 和 `/sandbox` 使用方式。（验证：执行 `/help`）
- [x] 每轮 system-reminder 包含 Workspace。（验证：检查 Fake Provider 收到的最后一条临时消息）
- [x] 每轮 system-reminder 包含 Plan 状态、权限模式和 Shell 策略。（验证：切换不同状态并检查请求）
- [x] 每轮 system-reminder 说明通常自动执行、可能 ASK 和硬拒绝边界。（验证：检查提醒文本）
- [x] 切换权限模式后下一轮提醒立即更新。（验证：比较切换前后两次请求）
- [x] 切换 Shell 策略后下一轮提醒立即更新。（验证：比较切换前后两次请求）
- [x] system-reminder 不写入 Conversation Context。（验证：模型请求结束后导出历史并扫描标签）
- [x] TUI 不显示完整权限文件内容、完整 Profile 或秘密环境变量。（验证：错误与审批输出敏感文本扫描）

## Agent Loop 与多工具集成

- [x] 每个工具调用独立经过 Plan、危险命令、路径敏感检查、规则和兜底决策。（验证：注入阶段 Spy 并检查调用顺序）
- [x] 硬边界命中后不执行后续权限阶段。（验证：分别对 Plan、危险命令、路径、敏感路径检查短路）
- [x] 已批准的相邻只读工具仍并发执行。（验证：屏障测试证明开始时间重叠）
- [x] 只读并发完成顺序不同，结果仍按模型原始顺序回灌。（验证：不同延迟 Fake Tool）
- [x] 写入、编辑和命令仍然串行执行。（验证：记录开始结束时间）
- [x] 某个工具规则错误只停止该工具，其他工具继续独立判断。（验证：多工具集成测试）
- [x] 某个工具被用户拒绝后，模型收到结构化拒绝并可以调整下一轮。（验证：Fake Provider 两轮流程）
- [x] 未知工具仍使本轮所有工具不执行并进入既有异常停止路径。（验证：现有未知工具回归测试）
- [x] Agent Loop 自然完成、12 轮上限、流式错误和用户取消行为保持不变。（验证：运行现有 Agent Loop 测试）
- [x] Plan Memory、`/do` 附加说明和无计划提示保持不变。（验证：运行现有 Runtime 与集成测试）
- [x] Token Usage 与 Prompt Cache 字段仍能正常展示。（验证：运行现有 usage 和 cache 测试）

## 编译、测试与打包

- [x] `artcode/security/dangerous_commands.yml` 被包含在构建产物中。（验证：构建 wheel 后列出归档内容）
- [x] `artcode/sandbox/seatbelt.sb` 被包含在构建产物中。（验证：构建 wheel 后列出归档内容）
- [x] 从安装后的 `artcode` 命令能够定位两份内置资源。（验证：在临时虚拟环境安装 wheel 并启动）
- [x] `python3 -m artcode` 能使用新的 Home、Workspace 和 Seatbelt 启动流程。（验证：从临时 Workspace 启动）
- [x] `artcode --workspace <目录>` 命令入口工作正常。（验证：安装后入口测试）
- [x] 所有单元测试通过。（验证：运行 `python3 -m pytest tests/unit`）
- [x] 所有确定性集成测试通过。（验证：运行权限、Agent Loop 和工具集成测试）
- [x] 真实 Seatbelt 集成测试全部通过且没有 skip。（验证：运行 `python3 -m pytest tests/integration/test_seatbelt_live.py -rs`）
- [x] 真实 DeepSeek 对话、Agent Loop 和工具测试通过。（验证：运行 `python3 -m pytest tests/integration/test_deepseek_live.py -rs`）
- [x] 真实 Prompt Cache 命中测试通过且 cached tokens 大于 0。（验证：运行 `python3 -m pytest tests/integration/test_prompt_cache_live.py -rs`）
- [x] 完整测试套件通过。（验证：运行 `python3 -m pytest`）
- [x] `git diff --check` 不报告空白错误。（验证：运行 `git diff --check`）

## 端到端场景

- [x] 场景一：从临时项目启动 ArtCode，不提供规则 → 启动面板显示该 Workspace、Default、Sandbox Auto 和 Seatbelt 成功 → 读取文件自动完成。（验证：真实 CLI 或确定性 Fake Provider）
- [x] 场景二：Default 下请求编辑普通文件 → 无匹配规则 → HITL 选择“仅本次允许” → 文件修改 → 本地权限文件不变化 → 模型总结结果。（验证：端到端集成测试）
- [x] 场景三：Default 下请求写普通文件 → HITL 选择“都允许” → 精确 ALLOW 写入本地级 → 下一次相同目标不再询问。（验证：两次连续 Agent Loop）
- [x] 场景四：任一层有效 DENY → 即使 Full 与 Sandbox Auto 也直接拒绝 → 工具未执行 → 模型收到规则来源。（验证：三层冲突端到端测试）
- [x] 场景五：Plan 下存在精确写入 ALLOW → 写工具仍然不可用 → 只读计划正常生成并保存。（验证：Plan 端到端测试）
- [x] 场景六：Sandbox Auto 执行普通项目命令 → 无 HITL → Workspace 写入成功 → 外部写入和网络被 Seatbelt 拒绝。（验证：真实 Seatbelt 测试）
- [x] 场景七：切换 Sandbox Ask → 普通命令弹出 HITL → 仅本次允许后仍在 Seatbelt 中执行。（验证：真实 CLI 或集成测试）
- [x] 场景八：确认切换 Sandbox Off → 普通命令仍需 HITL → 用户允许后使用普通 zsh → 界面持续显示无沙箱风险。（验证：真实 CLI）
- [x] 场景九：模型尝试读取主配置或修改权限文件 → 敏感路径层直接拒绝 → 不进入 HITL → 文件内容保持不变。（验证：文件工具与 Shell 两条路径）
- [x] 场景十：模型请求危险磁盘、Workspace 整体删除或 Git 强制清理命令 → 第一硬层直接拒绝 → 不读取规则、不进入沙箱。（验证：端到端 Fake Executor）
- [x] 场景十一：同轮包含读取、ASK 编辑、被拒绝命令和另一个读取 → 按原始顺序审批与回灌 → 未被拒绝的工具继续完成。（验证：多工具集成测试）
- [x] 场景十二：HITL 等待时按 `Ctrl+C` → 整个 Agent Loop 取消 → 当前与后续工具均未执行 → ArtCode 返回输入状态。（验证：真实 TUI 或异步集成测试）
- [x] 场景十三：运行期间将权限 YAML 改坏 → 下一工具指出具体文件并停止 → 修复后无需重启即可按新规则执行。（验证：热重载端到端测试）
- [x] 场景十四：Seatbelt Profile 在运行期间损坏 → 当前命令结构化失败 → 不降级普通 Shell → 后续仍可由用户处理。（验证：Profile 故障集成测试）
- [x] 场景十五：真实 DeepSeek 在 ch06 动态提醒下完成“读取—申请编辑—验证—总结”闭环，且 Conversation Context 中没有 system-reminder。（验证：真实 API 端到端测试）
