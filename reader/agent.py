import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx
from .config import ROOT
from .tools import definitions, execute, evidence_pages


class AgentError(Exception):
    pass


class CompletionClient:
    def __init__(self, config):
        self.config = config

    async def complete(self, messages, tools, required):
        payload = {'model': self.config.model, 'messages': messages, 'tools': tools,
                   'tool_choice': 'required' if required and self.config.require_tool_choice else 'auto',
                   'stream': False}
        if self.config.enable_thinking is not None:
            payload['enable_thinking'] = self.config.enable_thinking
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
                response = await client.post(self.config.base_url + '/chat/completions',
                    headers={'Authorization': 'Bearer ' + self.config.api_key},
                    json=payload)
            if response.status_code >= 400:
                # Do not expose provider bodies: they can contain credentials or document text.
                raise AgentError('模型服务返回 HTTP %d。请检查地址、模型名称、余额及 function calling 支持。' % response.status_code)
            body = response.json()
            message = body['choices'][0]['message']
            if not isinstance(message, dict):
                raise ValueError()
            return message
        except AgentError:
            raise
        except httpx.TimeoutException as exc:
            raise AgentError('模型服务超时，请稍后重试或检查服务地址。') from exc
        except httpx.HTTPError as exc:
            raise AgentError('无法连接模型服务，请检查网络及 OPENAI_BASE_URL。') from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AgentError('模型服务没有返回标准 Chat Completions 响应。') from exc


async def run_agent(question, library, config, client=None, max_rounds=10):
    if client is None and not config.configured:
        raise AgentError('尚未配置模型。请在项目 .env 中填写 API 地址、密钥和模型名称。')
    if not library.documents():
        raise AgentError('请先导入至少一份含可提取文字的 PDF。')
    client = client or CompletionClient(config)
    messages = [{'role': 'system', 'content': (ROOT / 'prompts/system.txt').read_text(encoding='utf-8')},
                {'role': 'user', 'content': question}]
    trace, evidence = [], {}
    tools = definitions(config.strict_tools)
    started = time.monotonic()
    for round_index in range(max_rounds):
        raw = await client.complete(messages, tools, required=not evidence)
        calls = raw.get('tool_calls') or []
        if calls:
            if not isinstance(calls, list) or len(calls) > 8:
                raise AgentError('单轮工具调用过多或格式无效，已停止。')
            assistant = {'role': 'assistant', 'content': raw.get('content'), 'tool_calls': calls}
            messages.append(assistant)
            for call in calls:
                try:
                    call_id = call['id']
                    name = call['function']['name']
                    arguments = call['function']['arguments']
                    if not all(isinstance(v, str) for v in (call_id, name, arguments)):
                        raise ValueError()
                except (KeyError, TypeError, ValueError) as exc:
                    raise AgentError('模型返回的工具调用格式无效。') from exc
                result = await asyncio.to_thread(execute, library, name, arguments)
                try:
                    display_arguments = json.loads(arguments)
                except (ValueError, TypeError):
                    display_arguments = {'invalid_json': arguments[:200]}
                trace.append({'step': len(trace)+1, 'tool': name, 'arguments': display_arguments, 'result': result})
                for item in evidence_pages(name, result):
                    evidence[(item['doc_id'], item['page'])] = item
                messages.append({'role': 'tool', 'tool_call_id': call_id,
                                 'content': json.dumps(result, ensure_ascii=False)})
            continue
        answer = raw.get('content')
        if not isinstance(answer, str) or not answer.strip():
            raise AgentError('模型返回了空回答。')
        # Check provenance, not semantic entailment. Both limits are explicit in the UI/README.
        citations = re.findall(r'\[([^\[\]\s:]+):p(\d+)\]', answer)
        cited = {(doc_id, int(page)) for doc_id, page in citations}
        unknown = cited - set(evidence)
        if unknown or (evidence and not cited):
            messages.extend([{'role': 'assistant', 'content': answer}, {'role': 'user', 'content':
                '引用校验未通过。仅使用本轮工具返回的 [文档ID:p页码] 引用。'
                '实质性回答至少给出一处引用；证据不足就说明不足并引用已检索页面。请修正。'}])
            continue
        if not evidence:
            answer = '当前材料中没有找到足够证据。检索未返回可引用原文，请换用关键词或导入相关材料。'
        documents = {d['id']: d for d in library.documents()}
        sources = [{'doc_id': d, 'page': p, 'name': documents[d]['name'],
                    'excerpt': evidence[(d, p)]['text'][:1500],
                    'url': '/api/documents/%s/file#page=%d' % (d, p)} for d, p in sorted(cited)]
        return {'id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(),
                'question': question, 'answer': answer, 'sources': sources, 'trace': trace,
                'model': config.model, 'elapsed_seconds': round(time.monotonic()-started, 2),
                'mode': 'live', 'citation_check': '仅校验引用来自已返回页面，不验证推论正确性'}
    raise AgentError('已达到 %d 轮调用上限，未生成通过引用校验的回答。请缩小问题或指定页码。' % max_rounds)
