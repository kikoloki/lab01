# BYOA 作业要求与实现核对

| 课程要求 | 本项目落实情况 | 可检查证据 |
| --- | --- | --- |
| 单一用途 Agent | 本地 PDF 阅读与有据问答 | `reader/agent.py`、浏览器工作台 |
| 至少两项不同功能 | SQLite 页级检索；独立解析原始 PDF 指定页；附文档目录查询 | `reader/library.py`、`reader/tools.py` |
| 标准上下文协议 | OpenAI 兼容 Chat Completions function calling | JSON Schema、`tool_call_id`、`role=tool` 回传 |
| AI 编写基础代码 | 接口、参数模型、调用循环、UI 与测试由 Codex 生成、运行并修正 | `docs/ai-development.md` |
| 仓库包含全部 Prompt | 系统提示独立保存，修正提示和示例问题可追溯 | `prompts/README.md` |
| 展示真实执行 | `qwen3.8-27b` 调用了目录、检索和读页工具 | `verification/positive-run.json` |
| 展示无证据处理 | 未提供成绩提升百分比时明确说明不足并引用原文 | `verification/unsupported-run.json` |
| 运行检查 | 13 项自动化测试通过；模拟协议测试与真实调用分开 | `tests/`、`verification/test-results.txt` |
| 简短报告 | 本地提交材料按原模板制作，不超过 5 页，含 4 张截图与反思 | 报告作为单独的课程提交文件 |

仓库地址：https://github.com/kikoloki/lab01 。报告作者的姓名与学号仅放在课程报告，不写入运行配置或 API 请求。

模型接入需要自己的 `.env`。原始用户文档、API Key、本机运行目录和虚拟环境均未纳入公开仓库。示例 PDF 与公开验证记录只含本项目原创的虚构材料。
