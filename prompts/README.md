# 项目全部 Prompt 的位置

开发交互提示词整理版见 [`development-prompts.md`](development-prompts.md)，按需求、工具、模型接入、界面、验证和课程交付阶段组织。

本项目不隐藏额外的系统提示。评阅者可按下表检查全部运行时提示和提问模板。

| 类型 | 源文件与位置 | 用途 |
| --- | --- | --- |
| 完整系统 Prompt | [`system.txt`](system.txt) | 定义本地阅读助手角色、先查再读、页码格式、证据不足处理及外部文本边界 |
| 引用修正反馈 | [`../reader/agent.py`](../reader/agent.py)，`引用校验未通过` 分支 | 把非法引用反馈给模型，要求重新回答 |
| 界面预设问题 | [`../static/app.js`](../static/app.js)，`prompts` 对象 | 概括核心内容、解释概念、查找局限 |
| 真实接入验证提问 | [`../scripts/verify_live.py`](../scripts/verify_live.py)，`question` | 用原创 PDF 检查工具调用和页码引用 |
| 实际运行问题与工具返回 | [`../verification/`](../verification/) | 保留成功问答及材料未提供数据的真实记录 |

应用通过 `messages` 传入系统提示和当前用户问题，通过 `tools` 传入 JSON Schema。工具返回内容作为 `role=tool` 消息回传，按 `tool_call_id` 对应原调用。界面中的历史问答便于阅读，不会自动作为上一轮上下文发送给模型。

## 系统 Prompt 的设计依据

- 角色提示：限定为围绕本地 PDF 作答的阅读助手。
- 工具使用：先列文档，再检索，并读取相关原文页。
- 检索增强上下文：事实来自本轮工具返回的页级文字。
- 反馈修正：引用不合法时由应用发出修正要求，最多 10 轮。

这些机制对应课件中的 Role prompting、Tool Use、RAG 和反馈修正思想；本项目不声称训练了模型，也不要求模型展示隐藏思维过程。
