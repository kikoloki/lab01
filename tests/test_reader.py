import asyncio
import io
import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from reader.library import Library, query_terms
from reader.tools import execute, definitions
from reader.agent import run_agent, CompletionClient, AgentError
from reader.config import Settings
from scripts.create_sample import make_pdf


@pytest.fixture
def library(tmp_path):
    pdf = tmp_path / 'sample.pdf'
    make_pdf(pdf)
    store = Library(tmp_path / 'data')
    store.ingest('cedar.pdf', pdf.read_bytes())
    return store


def test_extraction_search_read_and_persistence(library):
    doc = library.documents()[0]
    assert doc['page_count'] == 3
    hits = library.search('CEDAR-QX17', None, 5)['matches']
    assert hits[0]['page'] == 1 and '37 students' in hits[0]['text']
    assert 'Function calling' in library.read_page(doc['id'], 2, 0)['text']
    assert Library(library.root).documents() == library.documents()
    assert library.ingest('duplicate.pdf', (library.root / (doc['id']+'.pdf')).read_bytes()) == doc


def test_chinese_normalization_and_parameterized_query(library):
    doc_id = library.documents()[0]['id']
    with library.connect() as db:
        db.execute('UPDATE pages SET text=?, normalized=? WHERE doc_id=? AND page=3',
                   ('工具调用依赖本地原文', '工具调用依赖本地原文', doc_id))
    assert library.search('工具调用', None, 6)['matches'][0]['page'] == 3
    assert '工具' in query_terms('解释工具调用')
    library.search("'; DROP TABLE pages;--", None, 6)
    assert len(library.documents()) == 1


def test_invalid_pdf_and_image_only_pdf(library):
    with pytest.raises(ValueError, match='有效'):
        library.ingest('bad.pdf', b'not a PDF')
    pdf = PdfWriter(); pdf.add_blank_page(100, 100); buf = io.BytesIO(); pdf.write(buf)
    with pytest.raises(ValueError, match='OCR'):
        library.ingest('scan.pdf', buf.getvalue())


def test_pagination_and_tool_validation(library, monkeypatch):
    doc_id = library.documents()[0]['id']
    monkeypatch.setattr('pypdf._page.PageObject.extract_text', lambda self: 'a'*6200)
    first = library.read_page(doc_id, 1, 0)
    assert len(first['text']) == 6000 and first['next_start_char'] == 6000
    assert library.read_page(doc_id, 1, 6000)['next_start_char'] is None
    for name, arguments in [('read_pdf_page', {'doc_id': doc_id, 'page': 0, 'start_char': 0}),
        ('read_pdf_page', {'doc_id': doc_id, 'page': '1', 'start_char': 0}),
        ('read_pdf_page', {'doc_id': doc_id, 'page': 1, 'start_char': 0, 'path': '/etc/passwd'}),
        ('shell', {'command': 'ls'})]:
        assert 'error' in execute(library, name, json.dumps(arguments))
    assert 'error' in execute(library, 'search_library', '{invalid')
    assert 'error' in execute(library, 'read_pdf_page', json.dumps({'doc_id':doc_id,'page':99,'start_char':0}))
    for tool in definitions(True):
        schema = tool['function']['parameters']
        assert schema['additionalProperties'] is False
        assert set(schema.get('required', [])) == set(schema['properties'])


def call(name, args, call_id):
    return {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class ScriptedModel:
    """A protocol fixture, NOT a real LLM. Used only in isolated automated tests."""
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, required):
        self.requests.append(json.loads(json.dumps(messages)))
        return next(self.responses)


def test_standard_loop_returns_tools_and_rejects_fabricated_citation(library):
    doc_id = library.documents()[0]['id']
    model = ScriptedModel([
        {'tool_calls': [call('list_documents', {}, 'a')]},
        {'tool_calls': [call('search_library', {'query': 'CEDAR-QX17', 'doc_id': None, 'limit': 3}, 'b')]},
        {'tool_calls': [call('read_pdf_page', {'doc_id': doc_id, 'page': 1, 'start_char': 0}, 'c')]},
        {'content': '37 students [fake:p99]'},
        {'content': 'The fictional pilot enrolled 37 students [%s:p1]' % doc_id},
    ])
    result = asyncio.run(run_agent('How many students?', library, Settings('', '', 'fixture'), model))
    assert len(result['trace']) == 3
    assert result['sources'][0]['page'] == 1
    assert result['trace'][2]['tool'] == 'read_pdf_page'
    tool_messages = [m for m in model.requests[3] if m['role'] == 'tool']
    assert [m['tool_call_id'] for m in tool_messages] == ['a','b','c']


def test_no_tool_evidence_cannot_return_base_knowledge(library):
    model = ScriptedModel([{'content': 'The answer from memory is 42.'}])
    result = asyncio.run(run_agent('Unsupported?', library, Settings('', '', 'fixture'), model))
    assert '没有找到足够证据' in result['answer'] and not result['sources']


def test_round_limit(library):
    model = ScriptedModel([{'tool_calls': [call('list_documents', {}, 'a')]}]*2)
    with pytest.raises(AgentError, match='上限'):
        asyncio.run(run_agent('question', library, Settings('', '', 'fixture'), model, max_rounds=2))


def test_missing_configuration(library):
    with pytest.raises(AgentError, match='配置'):
        asyncio.run(run_agent('question', library, Settings('', '', '')))


def test_http_transport_payload_and_error_redaction(monkeypatch):
    original_client = httpx.AsyncClient
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        assert request.url.path == '/v1/chat/completions'
        if len(seen) == 1:
            return httpx.Response(200, json={'choices':[{'message':{'role':'assistant','content':'ok'}}]})
        return httpx.Response(401, text='do-not-expose-provider-secrets')
    monkeypatch.setattr('reader.agent.httpx.AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    client = CompletionClient(Settings('https://example.invalid/v1', 'test-key', 'test-model'))
    assert asyncio.run(client.complete([{'role':'user','content':'hello'}], definitions(), True))['content'] == 'ok'
    assert seen[0]['tool_choice'] == 'required' and len(seen[0]['tools']) == 3
    with pytest.raises(AgentError, match='401') as caught:
        asyncio.run(client.complete([], definitions(), False))
    assert 'do-not-expose' not in str(caught.value)


def test_qwen_compatible_auto_tools_and_thinking_flag(monkeypatch):
    original_client = httpx.AsyncClient
    def handler(request):
        body = json.loads(request.content)
        assert body['tool_choice'] == 'auto'
        assert body['enable_thinking'] is False
        assert len(body['tools']) == 3
        return httpx.Response(200, json={'choices':[{'message':{'role':'assistant','content':'ok'}}]})
    monkeypatch.setattr('reader.agent.httpx.AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    client = CompletionClient(Settings('https://example.invalid/v1', 'test-key', 'qwen-test',
                                        require_tool_choice=False, enable_thinking=False))
    asyncio.run(client.complete([], definitions(), True))


def test_local_api_endpoints(tmp_path, monkeypatch):
    from reader import app as module
    monkeypatch.setattr(module, 'library', Library(tmp_path / 'api-data'))
    monkeypatch.setattr(module, 'settings', lambda: Settings('', '', ''))
    client = TestClient(module.app)
    assert client.get('/').status_code == 200
    pdf = tmp_path / 'api.pdf'; make_pdf(pdf)
    upload = client.post('/api/documents', files={'file':('example.pdf',pdf.read_bytes(),'application/pdf')})
    assert upload.status_code == 200
    doc_id = upload.json()['id']
    assert client.get('/api/search', params={'q':'CEDAR-QX17'}).json()['matches'][0]['page'] == 1
    assert client.get('/api/documents/%s/pages/1' % doc_id).status_code == 200
    assert client.post('/api/ask', json={'question':'What is the count?'}).status_code == 400
    assert client.get('/api/documents/invalid/file').status_code == 404
    assert client.post('/api/documents', files={'file':('bad.pdf',b'bad')}).status_code == 400


def test_scoped_library_blocks_other_documents(library):
    from reader.library import ScopedLibrary
    doc_id = library.documents()[0]['id']
    scoped = ScopedLibrary(library, doc_id)
    assert len(scoped.documents()) == 1
    assert scoped.search('CEDAR-QX17', None, 2)['matches'][0]['doc_id'] == doc_id
    assert '37 students' in scoped.read_page(doc_id, 1, 0)['text']
    with pytest.raises(ValueError, match='仅可访问'):
        scoped.read_page('0'*16, 1, 0)
    with pytest.raises(ValueError, match='仅可访问'):
        scoped.search('question', '0'*16, 3)
    with pytest.raises(ValueError, match='不存在'):
        ScopedLibrary(library, '0'*16)


def test_sample_exports_and_scoped_api(library, monkeypatch):
    from reader import app as module
    monkeypatch.setattr(module, 'library', library)
    client = TestClient(module.app)
    doc_id = library.documents()[0]['id']
    assert client.get('/api/sample').content.startswith(b'%PDF-')
    for format in ['markdown', 'text', 'json']:
        result = client.get('/api/documents/%s/export' % doc_id, params={'format': format})
        assert result.status_code == 200 and 'CEDAR-QX17' in result.text
        assert 'attachment' in result.headers['content-disposition']
    exported = client.get('/api/documents/%s/export?format=json' % doc_id).json()
    assert len(exported['pages']) == 3
    assert client.get('/api/documents/%s/export?format=html' % doc_id).status_code == 400
    assert client.get('/api/documents/%s/export' % ('0'*16)).status_code == 404
    assert client.post('/api/ask', json={'question':'Question', 'doc_id':'0'*16}).status_code == 404
