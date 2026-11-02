# 贡献指南

欢迎提交 issue 与 pull request。以下类型的贡献尤其有价值：

- 可复现的失败案例，建议附上虚构对话与期望结果；
- 独立的虚构测试集，尤其是现有数据未覆盖的表达方式；
- 公平的对比实验与消融实验。

修改状态规则时，请说明触发条件与期望结果。确认值、待确认证据、历史版本与字节恢复应分别处理。

开发环境要求 Python 3.10 及以上。提交前请运行：

```sh
python -m unittest discover -s tests
ruff check src tests experiments examples
```

请勿提交真实聊天记录、真实数据库或任何密钥。修改 API 或数据库结构时，请说明兼容性与迁移方式。所有贡献以 MIT 许可证提供。
