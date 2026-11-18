# 多个助手共用一个本地项目库

每个项目绑定到一个独立 SQLite 文件。工具由各客户端启动，数据库文件可以在工作目录以外。项目库仅存用户明确要求保存的项目决定、调用端引用的用户原话、写入端和逐项版本历史。现有 Harness 自动摘要缓存和个人长期记忆库仍是独立存储。

## 开始使用

在已安装本仓库的虚拟环境中，从仓库根目录执行：

```sh
.venv/bin/python scripts/bind_project.py --workspace /absolute/path/workspace-A \
  --db ~/.memorygene/projects/example/decisions.sqlite --name mg_example
```

把 workspace-A 换为第二个工作目录，再运行一次，即可绑定同一项目。文件路径和解释器路径均为本机路径。复制到另一台机器需要重新绑定。请选择自己管理的项目目录，并保留客户端对项目配置的正常信任提示。

- **DSH**：在绑定的目录运行 `.memorygene/start-dsh`。脚本启动 TUI 并加载项目工具。已有桌面版用户可在绑定时指定 `--dsh-desktop`，下次加载该桌面 profile 后可用。
- **GPT / Codex**：在绑定的目录打开 Codex，批准自己信任的项目配置。若该版本只发现用户级 MCP，可显式使用 `codex mcp add NAME -- /absolute/path/.venv/bin/python -m memorygene.project serve --db /absolute/path/decisions.sqlite --client gpt`。此配置用于 Codex 客户端。
- **Claude Code / Desktop**：在绑定目录启动 Claude Code，通过正常提示启用该项目的 MCP。macOS Claude Desktop 可在绑定时加 `--claude-desktop`，保存其他工作后重新打开客户端。在桌面聊天中明确使用对应的项目工具。
- **Kimi Code**：打开绑定的项目目录，启动 Kimi Code，按客户端提示登录并确认项目。安装器写入项目级 `.kimi-code/mcp.json`。此配置用于 Kimi Code 客户端。
- **Grok Build**：绑定时加 `--grok`。在自己的项目中允许 Grok 使用项目配置，然后运行 `grok mcp doctor 项目工具名 --json` 检查连接。项目配置显式标记写入端为 Grok，版本历史可区分 Grok 与 Claude。

两个桌面选项及 Codex 用户级注册会在该客户端的其他会话中提供这个命名项目的工具。工作目录提示负责指导何时使用；文件持有者和已绑定客户端能读取该项目。这不构成按窗口鉴权。需要严格按工作区绑定时，仅使用项目级配置。请勿提交生成的含本机路径的配置。

## 在两个客户端之间交接

1. 在第一个助手中说：“当前任务是 release，请记住生产环境和测试环境的日志都保留 7 天。”
2. 在另一个助手中说：“接手 release。仅生产环境的日志改为保留 30 天，测试环境仍为 7 天。”
3. 回到原会话问：“两个环境各保留几天？请引用这次修改的原话。”

同一个任务应使用同一任务名和条目名。记录建议先按任务读取，找到旧条目后使用已有名称。现阶段键名是小写英文、数字、点、下划线或连字符；如果模型选了不同的键，会形成两条独立记录。工具返回原始引用和写入端，跨端引用没有经过另一端聊天记录的独立核验。

## 三项操作

- `project_read`：读取某个任务的当前决定，也可精确到一个条目。列表最多 20 条，超过会标明省略。
- `project_update`：提交单项修改，同时给出读到的版本与用户原话。第一次写入用 0。并发修改同一旧版本，只有一个写入成功，另一个收到冲突，需要重新读取并判断。
- `project_history`：读某条决定的最近 20 个版本，包含原话、值和记录方。指令约定在恢复任务和依赖某项决定的操作前读取。客户端是否实际调用要以工具记录为准。
