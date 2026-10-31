"""Run ONE real-provider check against an isolated, original demonstration PDF."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reader.config import settings
from reader.library import Library
from reader.agent import run_agent, AgentError


async def main():
    config = settings()
    if not config.configured:
        print('未运行：请先在 .env 填写 OPENAI_BASE_URL、OPENAI_API_KEY 和 OPENAI_MODEL。')
        return 2
    question = ('请先列出材料，再检索 Cedar 试点，读取相关 PDF 原文。'
                '材料中的试点编号和参与人数是什么？有哪些局限？请给出页码引用。')
    with tempfile.TemporaryDirectory(prefix='papertrail-check-') as folder:
        library = Library(folder)
        library.ingest('cedar-reading.pdf', (ROOT / 'examples/cedar-reading.pdf').read_bytes())
        try:
            result = await run_agent(question, library, config)
        except AgentError as exc:
            print('真实模型检查失败：', str(exc))
            return 1
    tools = {item['tool'] for item in result['trace']}
    checks = {'identifier_from_pdf': 'CEDAR-QX17' in result['answer'],
              'count_from_pdf': '37' in result['answer'],
              'citations_present': bool(result['sources']),
              'search_used': 'search_library' in tools,
              'pdf_reader_used': 'read_pdf_page' in tools}
    result['live_smoke_checks'] = checks
    folder = ROOT / 'evidence'; folder.mkdir(exist_ok=True)
    output = folder / ('live-check-' + result['id'] + '.json')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(result['answer'])
    print('\nChecks:', checks)
    print('Record:', output)
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
