"""PDF extraction and persistent, page-level local retrieval. No model involved."""
import hashlib
import io
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from pypdf import PdfReader

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 400


def normalize(text):
    return unicodedata.normalize('NFKC', text).lower()


def query_terms(query):
    text = normalize(query)
    words = re.findall(r'[a-z0-9_]+', text)
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        words.extend([run] if len(run) < 3 else [run[i:i+2] for i in range(len(run)-1)])
    return list(dict.fromkeys(words))[:32]


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'library.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, page_count INTEGER NOT NULL,
                  empty_pages INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS pages (
                  doc_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
                  normalized TEXT NOT NULL, PRIMARY KEY(doc_id, page));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.db), timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, name, content):
        if len(content) > MAX_BYTES:
            raise ValueError('PDF 超过 25 MB，请拆分后导入。')
        if not content.startswith(b'%PDF-'):
            raise ValueError('文件不是有效的 PDF。')
        doc_id = hashlib.sha256(content).hexdigest()[:16]
        with self.connect() as db:
            found = db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
            if found:
                return dict(found)
        try:
            pdf = PdfReader(io.BytesIO(content))
            if pdf.is_encrypted and not pdf.decrypt(''):
                raise ValueError('此 PDF 有密码，请先解密。')
            count = len(pdf.pages)
            if not 1 <= count <= MAX_PAGES:
                raise ValueError('仅支持 1–400 页的 PDF，请拆分文件。')
            texts = []
            for page in pdf.pages:
                stream = page.get_contents()
                if stream is not None and len(stream.get_data()) > 12 * 1024 * 1024:
                    raise ValueError('单页内容过大，请压缩或拆分 PDF。')
                texts.append(page.extract_text() or '')
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF 解析失败，请检查文件是否损坏。') from exc
        if not any(t.strip() for t in texts):
            raise ValueError('没有提取到文字。这可能是扫描件，请先做 OCR。')
        safe_name = Path(name.replace('\\', '/')).name[:180] or 'reading.pdf'
        result = {'id': doc_id, 'name': safe_name, 'page_count': count,
                  'empty_pages': sum(not t.strip() for t in texts)}
        (self.root / (doc_id + '.pdf')).write_bytes(content)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO documents VALUES (?, ?, ?, ?)', tuple(result.values()))
            db.executemany('INSERT OR IGNORE INTO pages VALUES (?, ?, ?, ?)',
                           [(doc_id, i+1, t, normalize(t)) for i, t in enumerate(texts)])
        return result

    def documents(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM documents ORDER BY name')]

    def export_document(self, doc_id):
        with self.connect() as db:
            document = db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
            if document is None:
                raise ValueError('文档不存在。')
            pages = [dict(row) for row in db.execute(
                'SELECT page, text FROM pages WHERE doc_id=? ORDER BY page', (doc_id,))]
        return {'document': dict(document), 'pages': pages}

    def search(self, query, doc_id, limit):
        terms = query_terms(query)
        if not terms:
            return {'matches': [], 'note': '请输入中文关键词或英文术语。'}
        clauses = ' OR '.join('instr(normalized, ?) > 0' for _ in terms)
        sql = 'SELECT doc_id, page, text, normalized FROM pages WHERE (' + clauses + ')'
        params = list(terms)
        if doc_id is not None:
            sql += ' AND doc_id=?'
            params.append(doc_id)
        with self.connect() as db:
            if doc_id and not db.execute('SELECT 1 FROM documents WHERE id=?', (doc_id,)).fetchone():
                raise ValueError('文档 ID 不存在，请先查看文档列表。')
            rows = db.execute(sql, params).fetchall()
        ranked = sorted(rows, key=lambda r: sum(min(r['normalized'].count(t), 8) for t in terms), reverse=True)
        matches = []
        for row in ranked[:limit]:
            # Locate in the original text, so normalization cannot corrupt excerpt offsets.
            positions = [row['text'].lower().find(t) for t in terms]
            start = max(0, min((p for p in positions if p >= 0), default=0)-180)
            matches.append({'doc_id': row['doc_id'], 'page': row['page'],
                            'text': row['text'][start:start+1500],
                            'citation': '[%s:p%d]' % (row['doc_id'], row['page'])})
        return {'query': query, 'matches': matches, 'method': '本地关键词与中文双字匹配，按词频排序'}

    def read_page(self, doc_id, page, start_char):
        with self.connect() as db:
            doc = db.execute('SELECT page_count FROM documents WHERE id=?', (doc_id,)).fetchone()
        if doc is None or not 1 <= page <= doc['page_count']:
            raise ValueError('文档或页码不存在，请检查文档列表。')
        # Independently read the original PDF; retrieval uses SQLite, this skill parses a PDF.
        try:
            pdf = PdfReader(self.root / (doc_id + '.pdf'))
            if pdf.is_encrypted:
                pdf.decrypt('')
            text = pdf.pages[page-1].extract_text() or ''
        except Exception as exc:
            raise ValueError('原始 PDF 读取失败，请检查本地文件是否完整。') from exc
        if start_char > len(text):
            raise ValueError('start_char 超过本页文字长度。')
        end = min(start_char + 6000, len(text))
        return {'doc_id': doc_id, 'page': page, 'text': text[start_char:end],
                'start_char': start_char, 'next_start_char': end if end < len(text) else None,
                'total_chars': len(text), 'citation': '[%s:p%d]' % (doc_id, page),
                'note': '本页未提取到文字，可能需要 OCR。' if not text.strip() else ''}


class ScopedLibrary:
    """Expose only the document selected in the reading workbench to the model."""
    def __init__(self, library, doc_id):
        self.library = library
        self.doc_id = doc_id
        if not any(d['id'] == doc_id for d in library.documents()):
            raise ValueError('文档不存在。')

    def documents(self):
        return [d for d in self.library.documents() if d['id'] == self.doc_id]

    def check(self, doc_id):
        if doc_id is not None and doc_id != self.doc_id:
            raise ValueError('当前问答仅可访问选中的文档。')

    def search(self, query, doc_id, limit):
        self.check(doc_id)
        return self.library.search(query, self.doc_id, limit)

    def read_page(self, doc_id, page, start_char):
        self.check(doc_id)
        return self.library.read_page(self.doc_id, page, start_char)
