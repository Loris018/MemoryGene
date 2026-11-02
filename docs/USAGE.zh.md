# 使用说明

这份说明讲怎么装 MemoryGene、怎么在 DeepSeek Harness 里用，以及平时会用到的命令。Harness 的接入细节见 [DSH-INTEGRATION.md](DSH-INTEGRATION.md)。

## 安装

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python scripts/install_dsh_skill.py                 # 项目级 Skill
.venv/bin/python scripts/install_dsh_skill.py --target user   # 或者：所有工作区都能用
.venv/bin/memorygene-dsh doctor                               # 看看用的是哪个库、哪个身份
```

数据库不会自动创建。第一次写入时加一次 `--allow-create`，之后就不要再加了，免得路径写错时悄悄多出一个新库。

装好之后，在 Harness 里新开一个会话，说"记住：我最喜欢玫瑰"，再开另一个会话问"我最喜欢什么花？"。判断有没有真的记住，不要看模型回没回"记住了"，而是看数据库里能不能查到：

```sh
.venv/bin/memorygene-dsh current --topic preference.favorite_flower
```

## 常用命令

下面用 `MG` 代表 `<项目>/.venv/bin/memorygene-dsh`。

### 查

```sh
"$MG" doctor                                          # 当前用的是哪个库、哪个身份
"$MG" recall --query "喜欢什么花"                       # 不知道 topic 时，按关键词找
"$MG" topics                                          # 列出所有主题
"$MG" current --topic preference.favorite_flower      # 现在的值
"$MG" history --topic preference.favorite_flower      # 全部历史，包括未确认的
"$MG" locate --topic preference.liked_flower --value "栀子花" --source "我喜欢的花是栀子花"
"$MG" review                                          # 自检：未解决的证据、疑似重复的主题、和原话对不上的值
"$MG" verify                                          # 只读的完整性检查
```

- `current` 返回 `null` 就是没有当前值，旧版本不会自己"复活"。
- `history` 里只有 `confirmed` 的条目才算历史事实。
- `recall` 是按字面匹配的，不懂同义词。它返回的 `unresolved` 是还没确认的说法，不能当答案。

### 写

```sh
"$MG" remember \
  --topic preference.favorite_flower \
  --value "玫瑰" \
  --source "我最喜欢玫瑰。" \
  --certainty explicit --intent assert --importance 0.8
```

写的时候要注意这几个字段：

- `--source` 必须是用户的原话，不能概括，也不能编。`--value` 里不要加原话里没有的信息，否则会收到 `unpaired_value` 提醒。
- `--certainty`：只有直接、明确的话才用 `explicit`。"也喜欢""还不错""可能""好像"一律用 `uncertain`；模型自己推断的用 `inferred`。
- `--intent`：默认 `assert`。只有用户明确改口（"现在最喜欢……""改成……"）才用 `change` 或 `correct`。
- 闲聊和一次性的内容不用写；如果写了，`--importance` 低于 0.5 的长期记忆会被直接丢掉。

返回的 `result.status` 说明发生了什么：

| 状态 | 含义 |
| --- | --- |
| `confirmed` | 成为当前值 |
| `pending` | 不确定或补充的说法，先留作证据，不算当前值 |
| `conflict` | 和当前值不同，但用户没说要改，需要确认 |
| `duplicate` | 和当前值一样，什么都不变 |
| `discarded` / `rejected_sensitive` / `expired` | 没有存下来 |

返回里还可能带 `advice`，大多数时候是空的：

- `confirm_change`：用户说了新的值，但没说"改成"。可以问一句，确认后用 `--intent change --resolves <evidence_id>` 再写一次。
- `possible_same_slot`：新主题可能和已有的某个主题是同一件事，确认后统一用旧主题。
- `repeated_uncertain`：同一个犹豫的说法在不同时间出现了两次以上，可以找机会问一下。
- `unpaired_value`：值在原话里找不到，或者原话其实是否定的。

### 改、过期、忘

```sh
# 用户明确改口
"$MG" remember --topic preference.favorite_flower --value "栀子花" \
  --source "现在最喜欢栀子花了。" --certainty explicit --intent change --importance 0.8

# 有有效期的信息
"$MG" remember --topic promotion.code --value "FICTIONAL-CODE" \
  --source "优惠码是 FICTIONAL-CODE，11 月 1 日前有效。" --expires-at 2026-11-01T00:00:00Z

# 遗忘一个主题（连同全部历史一起删除）
"$MG" forget --topic preference.favorite_flower
```

过期是在读取时过滤掉，不会在后台删除数据。`forget` 是逻辑删除，SQLite 的空闲页、系统快照和外部备份不在它的处理范围内。

### 敏感信息

住址、证件、联系方式、健康这类信息必须有用户明确同意的原话：

```sh
"$MG" remember --topic profile.address --value "虚构路1号" \
  --source "我住在虚构路1号。" --sensitive \
  --consent --consent-evidence "可以记住这个地址"
```

没有同意原话时，适配器会直接拒绝。只加 `--consent` 这个开关也不够。

### 任务接续

用户明确要求"把进度存一下"时才用。具体格式见 [TASKS.zh.md](TASKS.zh.md)。

```sh
"$MG" task-save --task my-project --file /absolute/path/task.json
"$MG" task-show --task my-project
"$MG" task-resume --checkpoint-id <ID> --allow-cross-session
"$MG" task-forget --task my-project
```

### 数据损坏

读到损坏的记录会直接报 `IntegrityError`，不会返回猜测的值。可以用 `"$MG" repair --event-id <id>` 从校验通过的副本恢复；两份都坏了就只能报错。

## 测试

```sh
.venv/bin/python -m unittest discover -s tests       # 单元和集成测试
.venv/bin/python scripts/acceptance.py               # 库级验收，不调用模型
.venv/bin/python scripts/e2e_harness.py              # 真实 Harness 会话，会调用模型
```

不要在自己真正在用的数据库上跑验收脚本，它们会用单独的测试库。

## 卸载

```sh
.venv/bin/python scripts/install_dsh_skill.py --uninstall                # 项目级
.venv/bin/python scripts/install_dsh_skill.py --target user --uninstall  # 用户级
.venv/bin/python scripts/install_global_auto.py --uninstall              # 关掉全局提示
```

默认会保留数据库。加 `--purge-db` 会连数据库一起删除，删之前先备份。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 模型说没有 memorygene 这个 Skill | 会话目录不在项目里；换到项目目录，或者装用户级 |
| `No MemoryGene database configured` | 到项目根目录运行，或者用 `--db` 指定数据库 |
| `Refusing to create a new database` | 这是保护机制；确定要新建库时才加 `--allow-create` |
| `IntegrityError` | 数据损坏，先试 `repair --event-id` |
| 模型只回了一句"记住了" | 让它把实际执行的命令和返回结果贴出来，或者自己用 `current` 查一下 |
