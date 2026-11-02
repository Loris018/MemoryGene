# 首次尝试：模型按安全规则拒绝隐式建库

第一次运行 `scripts/e2e_harness.py` 前没有显式创建测试库。真实 headless 会话 A 读取
skill 后执行 `doctor` 得到 `ready:false`，随后 `current` 报
`Refusing to create a new database implicitly`，于是模型**没有写入**，明确报告未保存。

这是预期的安全行为（防止切换聊天后误建新库），也说明 skill 的“不得隐式建库”规则
在真实对话里生效。随后验收脚本改为先显式执行一次
`memorygene-dsh --allow-create topics` 创建测试库（测试夹具的显式初始化），再跑正式
会话；正式证据见上一级目录的 `A-write-*` 等文件。
