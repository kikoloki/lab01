"""Standard Chat Completions function schemas and validated dispatch."""
import json
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ListDocuments(Arguments):
    pass


class SearchLibrary(Arguments):
    query: str = Field(min_length=1, max_length=200)
    doc_id: Optional[str] = Field(description='文档 ID，null 表示搜索全部文档')
    limit: int = Field(ge=1, le=8)


class ReadPage(Arguments):
    doc_id: str = Field(min_length=16, max_length=16)
    page: int = Field(ge=1, le=400)
    start_char: int = Field(ge=0, description='从 0 开始的字符偏移，首次阅读填 0')


REGISTRY = {
    'list_documents': (ListDocuments, '查看本地 PDF 文档的 ID、文件名、页数和空白页数量。'),
    'search_library': (SearchLibrary, '在本地 SQLite 页级文本库检索中英文关键词，返回原文片段和页码。'),
    'read_pdf_page': (ReadPage, '读取 PDF 的指定物理页原文，每次最多 6000 字符，可按偏移继续阅读。'),
}


def definitions(strict=False):
    result = []
    for name, (model, description) in REGISTRY.items():
        schema = model.model_json_schema()
        schema.pop('title', None)
        result.append({'type': 'function', 'function': {
            'name': name, 'description': description, 'parameters': schema, 'strict': strict}})
    return result


def execute(library, name, raw_arguments):
    if name not in REGISTRY:
        return {'error': '未知工具。只能调用已注册工具。'}
    try:
        args = REGISTRY[name][0].model_validate_json(raw_arguments)
        if name == 'list_documents':
            return {'documents': library.documents()}
        if name == 'search_library':
            return library.search(args.query, args.doc_id, args.limit)
        return library.read_page(args.doc_id, args.page, args.start_char)
    except ValidationError:
        return {'error': '参数不符合工具 JSON Schema，请检查字段、类型、范围及必填参数。'}
    except ValueError as exc:
        return {'error': str(exc)}


def evidence_pages(name, result):
    if 'error' in result:
        return []
    if name == 'read_pdf_page':
        return [result] if result.get('text', '').strip() else []
    if name == 'search_library':
        return result.get('matches', [])
    return []
