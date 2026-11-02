# GUI 人工验收脚本化记录

目标：在真实 DeepSeek Harness 桌面 GUI 中人工走完跨会话/修订/历史/遗忘，并把每一步变成可复核文件。
仍然需要你亲手发消息；脚本只做隔离测试库的机器核对，不会碰生产库。

## 工作区

`../MemoryGene-GUI-test-2026-10-27/`（独立的 git 工作区、独立 `var/gui-test.db`、namespace=`gui-acceptance`、
subject=`fictional-user`）。已预装项目级 Skill 与配置。

## 步骤

1. 在 Harness 中 **Add workspace / 选择** 上述目录，新建会话 A：
   > 请使用 memorygene skill，记住：我最喜欢玫瑰。
   然后运行核对：

   ```sh
   cd "<repo>"
   .venv/bin/python scripts/gui_acceptance_verify.py --phase preflight
   .venv/bin/python scripts/gui_acceptance_verify.py --phase after-a
   ```

2. 在同一工作区新开会话 B：
   > 请使用 memorygene skill，我最喜欢什么花？然后：栀子花也好看。再然后：现在最喜欢栀子花了。
   核对：

   ```sh
   .venv/bin/python scripts/gui_acceptance_verify.py --phase after-b
   ```

3. 新开会话 C：
   > 请使用 memorygene skill，忘掉 preference.favorite_flower 这个主题。
   核对：

   ```sh
   .venv/bin/python scripts/gui_acceptance_verify.py --phase after-c
   ```

## 结果

每次核对写入 `<项目>/evidence/10-gui-acceptance/<phase>.json`（passed/checks/实际数据库值）。
只有四个 phase 都通过，才把 GUI 人工验收标记为完成；当前只有 preflight 可先跑，结论会明确写“仍需人工消息”。
注意：不要在生产项目上执行这套“忘记”步骤；测试库与生产库是分开的。
