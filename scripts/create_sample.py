"""Generate a small, original text PDF using only the runtime's pypdf dependency."""
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

PAGES = [
    ['Papertrail demonstration reading', 'Original fictional material for integration testing.',
     '', 'Project: Cedar classroom reading pilot', 'The pilot identifier is CEDAR-QX17.',
     'The pilot enrolled 37 students in two reading sessions.',
     'This identifier and count are synthetic facts in this local PDF.',
     'They are not results from a real educational study.'],
    ['Method: a tool-assisted reading workflow', '',
     'The assistant first lists available PDF documents.',
     'It searches a local SQLite page index for relevant keywords.',
     'It then reads the original page text and cites physical page numbers.',
     'Function calling bridges the language model and local tools.',
     'The model chooses tool names and structured JSON arguments.',
     'The application validates arguments before executing a tool.'],
    ['Limitations and evaluation', '',
     'Scanned image PDFs require OCR before text extraction.',
     'Keyword search can miss synonyms and complex semantic relations.',
     'A page citation establishes provenance, not factual entailment.',
     'No improvement in learning outcomes was measured in this fictional pilot.',
     'The reading assistant should abstain when the evidence is missing.',
     'Evaluation should include valid citations and unsupported questions.']
]


def make_pdf(path):
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    for lines in PAGES:
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        commands = ['BT /F1 12 Tf 48 780 Td 23 TL']
        for line in lines:
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append('(%s) Tj T*' % escaped)
        commands.append('ET')
        stream.set_data('\n'.join(commands).encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    with Path(path).open('wb') as output:
        writer.write(output)


if __name__ == '__main__':
    target = Path(__file__).resolve().parent.parent / 'examples/cedar-reading.pdf'
    make_pdf(target)
    print('Created:', target)
