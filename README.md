# 跨助手共享任务记忆

在一个 AI 助手里修改要求，换一个助手还能查到最新决定、适用范围和修改依据。DeepSeek Harness、Codex 和 Grok Build 可以从不同工作目录连接同一个本地 SQLite 库。

[下载安装包](https://github.com/Loris018/MemoryGene/archive/refs/heads/main.zip) · [连接已有工作目录](docs/FOUR-CLIENT-PROJECT.zh.md) · [English](#english)

## 安装

需要 Python 3.10 或更高版本。macOS 和 Linux 还需要 Git。使用前请登录所选的助手客户端。

| 系统 | 安装方式 |
| --- | --- |
| macOS | 下载并解压上方 ZIP，双击 `Install.command`。 |
| Windows | 将 ZIP 解压到打算长期保留的目录，双击 `Install-Windows.cmd`。客户端会继续使用该目录中的 Python 环境。 |
| Linux | 在终端运行下方命令。macOS 也可以使用这条命令。 |

```sh
mg_installer=$(mktemp) && curl -fsSL https://raw.githubusercontent.com/Loris018/MemoryGene/main/install.sh -o "$mg_installer" && bash "$mg_installer"
```

安装完成后，在助手中打开主目录下的 `MemoryGene-Demo`。Codex 和 Grok Build 从该目录启动；DeepSeek Harness 在 macOS/Linux 上使用目录内的 `.memorygene/start-dsh-turns` 启动。首次连接时，按客户端提示确认项目工具。要用于已有项目，可以把多个工作目录绑定到同一数据库。[配置指南](docs/FOUR-CLIENT-PROJECT.zh.md)

## 跨助手使用

例如，生产和测试环境原先都保留 7 天日志。只延长生产环境时，可以这样交接：

| 在哪里 | 对助手说 |
| --- | --- |
| DeepSeek Harness | “记到 `release` 任务里：生产环境和测试环境的日志都保留 7 天。” |
| Codex 或 Grok Build | “接手 `release`。先查现行约定，然后记下修改：仅生产环境延长到 30 天，测试环境仍为 7 天。” |
| 回到原会话 | “继续 `release`。两个环境现在各保留几天？给我上一次修改的原话。” |

每个决定都有版本和记录它的客户端。两个助手基于同一旧版本修改同一条目时，第二次写入会收到冲突提示，可以重新读取后再决定如何合并。历史保留写入方引用的原话，方便核对“仅生产环境”这样的限定。

## 接手续做中的任务

在第一个助手中说：“做库存导出工具，列出商品编号和库存。字段已核对，下一步是计算合计。” 换一个助手后，说：“继续做库存导出，先告诉我做到哪了，再完成下一步。” 任务卡分别保存目标、要求、进度、待办、来源和版本。描述可能指向多个任务时，助手应先让你选择。

安装器在示例目录配置逐轮读取与短期上下文采集。Codex 用户需在 `/hooks` 或桌面端 **Review hooks** 中核对并启用命令；Grok Build 需要信任该目录。工作区可按任务选用编程或教学模式，任务偏好优先于该库的默认偏好。当前对话中的新指示优先。有关临时数据、冲突处理和接续检查，见[工作区指南](docs/FOUR-CLIENT-PROJECT.zh.md)。

## 客户端与数据

- **共享决定**支持 DeepSeek Harness、Codex 和 Grok Build。两个客户端连接同一个库后，就可以按任务读取和修改决定。[客户端配置](docs/FOUR-CLIENT-PROJECT.zh.md)
- **后台任务卡**是 DeepSeek Harness 的可选插件，可记录待办、保存来源，并在要求改变时提示复查相关成果。需要在 Harness 中单独启用。[插件说明](plugins/dsh-memorygene-auto/README.md)
- **数据存储**使用本机明文 SQLite。助手读到的内容会进入该客户端的模型上下文。可选后台插件会向宿主配置的模型服务发送有限的对话片段。[数据与隐私](SECURITY.md)

[个人记忆用法](docs/USAGE.zh.md) · [贡献指南](CONTRIBUTING.md) · [MIT 许可](LICENSE)

---

<a id="english"></a>

## Shared task memory for AI assistants

Keep project decisions in a local SQLite database that DeepSeek Harness, Codex and Grok Build can access from different working directories. Each assistant can look up the current decision, its scope and the words recorded when it changed.

### Installation

Install Python 3.10 or later and sign in to your assistant. macOS and Linux also require Git. [Download the ZIP](https://github.com/Loris018/MemoryGene/archive/refs/heads/main.zip).

| Platform | Steps |
| --- | --- |
| macOS | Extract the ZIP and double-click `Install.command`. |
| Windows | Extract the ZIP into a permanent folder and double-click `Install-Windows.cmd`. Clients use the Python environment in that folder. |
| Linux or macOS terminal | Run the command below. |

```sh
mg_installer=$(mktemp) && curl -fsSL https://raw.githubusercontent.com/Loris018/MemoryGene/main/install.sh -o "$mg_installer" && bash "$mg_installer"
```

Open `MemoryGene-Demo` in your home directory. Start Codex or Grok Build there. For DeepSeek Harness on macOS or Linux, run `.memorygene/start-dsh-turns` inside that directory. Approve the project tools when prompted. To use an existing project, bind its working directories to the same database. [Client setup](docs/INTEGRATIONS.md)

### Example handoff

1. In DeepSeek Harness, say “For the `release` task, remember that production and test logs are both kept for 7 days.”
2. In Codex or Grok Build, say “Take over `release`. Check the current policy, then record this change: keep production logs for 30 days and test logs for 7 days.”
3. Return to the original session and ask “How long do we keep logs in each environment? Quote the last change.”

Each entry has a version and a writing client. If two clients edit the same version, the second receives a conflict and can reread the entry before merging. The history retains the source quote supplied by the client that wrote it.

### Continue a task

Start a task in one client, record its goal, requirements, completed steps and next action, then describe it in another client. Task cards preserve versioned entries and their sources. Ask the assistant to finish the next open step. When several tasks fit, choose one before continuing. Tasks can select coding or study guidance and override workspace defaults.

The starter workspace includes per-turn hooks for short local lookups and temporary evidence capture. In Codex, review and enable both commands in `/hooks` or **Review hooks**. Grok Build requires project trust. Use the project tools to retrieve a full card, check what changed after compaction or resolve incompatible proposals. [Workspace guide](docs/FOUR-CLIENT-PROJECT.zh.md)

### Clients and storage

- **Shared decisions:** Connect DeepSeek Harness, Codex or Grok Build to the same database to read and update decisions by task.
- **Background task cards:** An optional DeepSeek Harness plugin tracks next steps, links notes to source excerpts and flags recorded dependencies for review when a requirement changes. [Plugin guide](plugins/dsh-memorygene-auto/README.md)
- **Privacy:** The local SQLite file is unencrypted. Retrieved records enter the assistant's model context. The optional plugin sends bounded excerpts to the host's configured model provider. [Security](SECURITY.md)

[Contributing](CONTRIBUTING.md) · [MIT license](LICENSE)
