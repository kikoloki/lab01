import json
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .config import ROOT, settings
from .library import Library, ScopedLibrary, MAX_BYTES
from .agent import AgentError, run_agent

app = FastAPI(title='Papertrail · 本地 PDF 阅读助手', version='1.0.0')
library = Library(ROOT / 'data')
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')
pdfjs_path = ROOT / 'node_modules/pdfjs-dist'
if pdfjs_path.exists():
    app.mount('/vendor/pdfjs', StaticFiles(directory=str(pdfjs_path)), name='pdfjs')


@app.get('/')
def home():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/api/status')
def status():
    cfg = settings()
    return {'configured': cfg.configured, 'model': cfg.model,
            'documents': len(library.documents()), 'protocol': 'Chat Completions function calling'}


@app.get('/api/documents')
def documents():
    return library.documents()


@app.get('/api/sample')
def sample_document():
    return FileResponse(ROOT / 'examples/cedar-reading.pdf', media_type='application/pdf')


@app.post('/api/documents')
async def upload(file: UploadFile = File(...)):
    try:
        content = await file.read(MAX_BYTES+1)
        return await run_in_threadpool(library.ingest, file.filename or 'reading.pdf', content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()


def document_path(doc_id):
    if doc_id not in {d['id'] for d in library.documents()}:
        raise HTTPException(404, '文档不存在。')
    return ROOT / 'data' / (doc_id + '.pdf')


@app.get('/api/documents/{doc_id}/file')
def pdf_file(doc_id: str):
    return FileResponse(document_path(doc_id), media_type='application/pdf')


@app.get('/api/documents/{doc_id}/pages/{page}')
def page_text(doc_id: str, page: int, start_char: int = 0):
    if start_char < 0:
        raise HTTPException(400, '字符偏移不能为负数。')
    try:
        return library.read_page(doc_id, page, start_char)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/api/documents/{doc_id}/export')
def export_document(doc_id: str, format: str = 'markdown'):
    try:
        data = library.export_document(doc_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if format == 'json':
        content = json.dumps(data, ensure_ascii=False, indent=2)
        media_type, extension = 'application/json', 'json'
    elif format == 'markdown':
        content = '# ' + data['document']['name'] + '\n\n' + '\n\n'.join(
            '## 第 %d 页\n\n%s' % (p['page'], p['text']) for p in data['pages'])
        media_type, extension = 'text/markdown', 'md'
    elif format == 'text':
        content = '\n\n'.join('第 %d 页\n%s' % (p['page'], p['text']) for p in data['pages'])
        media_type, extension = 'text/plain', 'txt'
    else:
        raise HTTPException(400, '不支持的导出格式。')
    return Response(content, media_type=media_type,
                    headers={'Content-Disposition': 'attachment; filename="%s.%s"' % (doc_id, extension)})


@app.get('/api/search')
def search(q: str, doc_id: Optional[str] = None):
    if not q.strip() or len(q) > 200:
        raise HTTPException(400, '请输入 1–200 字的关键词。')
    try:
        return library.search(q, doc_id, 6)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=3000)
    doc_id: Optional[str] = Field(default=None, min_length=16, max_length=16)


@app.post('/api/ask')
async def ask(body: Question):
    try:
        context = ScopedLibrary(library, body.doc_id) if body.doc_id else library
        result = await run_agent(body.question, context, settings())
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(400, str(exc)) from exc
    result['doc_id'] = body.doc_id
    folder = ROOT / 'evidence'
    folder.mkdir(exist_ok=True)
    (folder / (result['id'] + '.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
