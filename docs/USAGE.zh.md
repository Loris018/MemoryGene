# 使用说明

本文介绍 MemoryGene 的安装、在 DeepSeek Harness 中的使用方式以及常用命令。Harness 接入细节见 [DSH-INTEGRATION.md](DSH-INTEGRATION.md)。

## 安装

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python scripts/install_dsh_skill.py                 # 项目级 Skill
.venv/bin/python scripts/install_dsh_skill.py --target user   # 或：用户级 Skill，对所有工作区生效
.venv/bin/memorygene-dsh doctor                               # 查看当前使用的数据库与身份
```

数据库不会自动创建。首次写入时需添加一次 `--allow-create`，之后不应再使用该参数，以避免路径配置错误时意外创建新库。

安装完成后，可在 Harness 中新建会话并输入"记住：我最喜欢玫瑰"，再在另一个会话中询问"我最喜欢什么花？"。验证是否写入成功应以数据库查询结果为准，而非模型的口头回复：

```sh
.venv/bin/memorygene-dsh current --topic preference.favorite_flower
```

## 常用命令

下文以 `MG` 表示 `<项目>/.venv/bin/memorygene-dsh`。

### 查询

```sh
"$MG" doctor                                          # 当前数据库与身份
"$MG" recall --query "喜欢什么花"                       # 未知 topic 时按关键词检索
"$MG" topics                                          # 列出全部主题
"$MG" current --topic preference.favorite_flower      # 当前值
"$MG" history --topic preference.favorite_flower      # 完整历史，含未确认证据
"$MG" locate --topic preference.liked_flower --value "栀子花" --source "我喜欢的花是栀子花"
"$MG" review                                          # 自检：未解决证据、疑似重复主题、与原话不符的值
"$MG" verify                                          # 只读完整性检查
```

- `current` 返回 `null` 表示当前没有有效值，旧版本不会自动恢复。
- `history` 中仅状态为 `confirmed` 的条目可视为历史事实。
- `recall` 基于字面匹配，不处理同义词；其返回的 `unresolved` 为尚未确认的证据，不应作为答案使用。

### 写入

```sh
"$MG" remember \
  --topic preference.favorite_flower \
  --value "玫瑰" \
  --source "我最喜欢玫瑰。" \
  --certainty explicit --intent assert --importance 0.8
```

字段要求：

- `--source` 必须为用户原话，不得概括或编造；`--value` 不应包含原话中没有的信息，否则将返回 `unpaired_value` 提示。
- `--certainty`：仅直接、明确的陈述使用 `explicit`；"也喜欢""还不错""可能""好像"等使用 `uncertain`；模型推断使用 `inferred`。
- `--intent`：默认为 `assert`；仅当用户明确改变（"现在最喜欢……""改成……"）时使用 `change` 或 `correct`；"X 也不错"使用 `supplement`（只作为证据保留）；用户明确撤回（"我不再喜欢玫瑰了"）时使用 `retract`，`--value` 填被撤回的当前值。
- 闲聊与一次性内容无需写入；长期记忆的 `--importance` 低于 0.5 时将被丢弃。

返回结果中 `result.status` 的含义：

| 状态 | 含义 |
| --- | --- |
| `confirmed` | 成为当前值 |
| `pending` | 不确定或补充性陈述，作为证据保留，不成为当前值 |
| `conflict` | 与当前值不同且用户未声明改变，需要确认 |
| `duplicate` | 与当前值相同，状态不变 |
| `discarded` / `rejected_sensitive` / `expired` | 未写入（`discarded` 只留 30 天匿名痕迹，用于判断是否反复出现） |

默认情况下，与当前值不同、但未声明改变的陈述会进入 `conflict`，等待用户确认。若部署场景中无人可确认，可在写入时加 `--update latest`，或在适配器配置中设置 `"update_policy": "latest"`：此时较新的明确陈述会直接成为当前值，并在历史中标记。

返回结果还可能包含 `advice`（多数情况下为空）：

- `confirm_change`：用户给出了新值但未声明改变。可向用户确认，确认后使用 `--intent change --resolves <evidence_id>` 重新写入。
- `possible_same_slot`：新主题可能与已有主题指向同一属性，确认后应统一使用已有主题。
- `repeated_uncertain`：同一不确定陈述已在不同时间出现两次以上，可在合适时机向用户确认。
- `auto_updated`：`latest` 模式下，未声明改变的陈述已替换旧值。相关时可向用户说明这一变化，以便其更正。
- `recurring_low_importance`：一件原本被判为不重要的小事，已在 3 个不同的日子被提到。可在合适时问用户一次是否要记住，同意后以更高的 `--importance` 重新写入。
- `unpaired_value`：值在原话中找不到，或原话为否定表述。

## 用户画像

主题名的第一段决定类别：`profile.*` 基本信息（城市、职业、生日），`preference.*` 偏好，`recent.*` 近期状态（烦恼、心情、最近在忙的事），`life.*` 闲聊中提到的个人经历，`project.*` 用户做过或正在做的项目。

`recent.*` 写入时若未指定 `--expires-at`，默认 30 天后到期（配置项 `recent_days` 可改）；用户再次提到同一内容时自动续期。到期后不再算作当前状态，但保留在历史中。

```sh
"$MG" profile      # 按类别列出当前画像，每项附用户原话；已到期的近期状态列在 past_situations
```

### 修改、到期与遗忘

```sh
# 用户明确改变
"$MG" remember --topic preference.favorite_flower --value "栀子花" \
  --source "现在最喜欢栀子花了。" --certainty explicit --intent change --importance 0.8

# 带有效期的信息
"$MG" remember --topic promotion.code --value "FICTIONAL-CODE" \
  --source "优惠码是 FICTIONAL-CODE，11 月 1 日前有效。" --expires-at 2026-11-01T00:00:00Z

# 用户撤回当前值（当前值变为空，历史保留）
"$MG" remember --topic preference.favorite_flower --value "栀子花" \
  --source "我不再喜欢栀子花了。" --certainty explicit --intent retract

# 遗忘某一主题（含全部历史）
"$MG" forget --topic preference.favorite_flower
```

到期在读取时过滤，不进行后台删除。`forget` 为逻辑删除，不涵盖 SQLite 空闲页、系统快照与外部备份。

### 敏感信息

住址、证件、联系方式、健康等信息必须附带用户明确同意的原话：

```sh
"$MG" remember --topic profile.address --value "虚构路1号" \
  --source "我住在虚构路1号。" --sensitive \
  --consent --consent-evidence "可以记住这个地址"
```

缺少同意原话时适配器将直接拒绝；仅提供 `--consent` 开关不构成同意证据。

### 助手对用户的看法

助手可以根据记忆形成对用户的看法，但每条看法都必须引用具体记忆：

```sh
"$MG" impression-save --text "喜欢攀岩、爬山这类户外运动" --cite <记忆的 event_id> --cite <另一条>
"$MG" impressions                 # 列出看法及其依据（原话）；stale 表示依据已变化
"$MG" impression-forget --id <id>  # 删除一条；--all 删除全部
```

依据的记忆被修改、撤回、到期或删除后，看法自动失效；删除某个记忆主题时，引用它的看法会一并删除。

### 任务接续

仅在用户明确要求保存进度时使用，格式说明见 [TASKS.zh.md](TASKS.zh.md)。

```sh
"$MG" task-save --task my-project --file /absolute/path/task.json
"$MG" task-show --task my-project
"$MG" task-resume --checkpoint-id <ID> --allow-cross-session
"$MG" task-forget --task my-project
```

### 数据损坏

读取到损坏记录时将返回 `IntegrityError`，不会返回推测值。可使用 `"$MG" repair --event-id <id>` 从校验通过的副本恢复；主副本均损坏时将报错。

## 测试

```sh
.venv/bin/python -m unittest discover -s tests       # 单元与集成测试
.venv/bin/python scripts/acceptance.py               # 库级验收，不调用模型
.venv/bin/python scripts/e2e_harness.py              # 真实 Harness 会话，将调用模型
```

验收脚本使用独立的测试数据库，请勿在实际使用的数据库上运行。

## 卸载

```sh
.venv/bin/python scripts/install_dsh_skill.py --uninstall                # 项目级
.venv/bin/python scripts/install_dsh_skill.py --target user --uninstall  # 用户级
.venv/bin/python scripts/install_global_auto.py --uninstall              # 移除全局提示
```

默认保留数据库。添加 `--purge-db` 将同时删除数据库，请提前备份。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 模型提示不存在 memorygene Skill | 会话工作目录不在项目内；切换至项目目录，或改用用户级安装 |
| `No MemoryGene database configured` | 在项目根目录运行，或通过 `--db` 指定数据库 |
| `Refusing to create a new database` | 保护机制；确需新建时再添加 `--allow-create` |
| `IntegrityError` | 数据损坏，可尝试 `repair --event-id` |
| 模型仅回复"记住了" | 要求模型展示实际执行的命令与返回结果，或使用 `current` 自行核验 |
