"""Read-only checks of article identity, content, and failure side effects."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def check_result(value: dict, actual: dict, expected: dict) -> list[str]:
    failures = []
    if actual['input'] != {'raw_input': value['raw_input'], 'processed_input': {'page_id_file': value['page_id_file'], 'article_file': value['article_file']}}:
        failures.append('Input was not preserved.')
    if actual['output_format'] != 'markdown':
        failures.append('Expected Markdown output format.')
    root = Path(os.environ['PROJECT_TRANSACTION_DATA_DIRECTORY'])
    if actual['status'] == 'error':
        if actual['output'] is not None or actual['meta_data'] != {}:
            failures.append('Errors must have null output and empty metadata.')
        if expected.get('error_code', actual['error']['code']) != actual['error']['code']:
            failures.append('Unexpected error code.')
        if list(root.iterdir()):
            failures.append('Rejected input wrote an artifact in the isolated destination.')
        return failures
    project = Path(os.environ['PROJECT_TRANSACTION_INPUT_ROOT'])
    page_id = json.loads((project / value['page_id_file']).read_text(encoding='utf-8'))['page_id']
    url = actual['meta_data'].get('url', '')
    if actual['meta_data'] != {'page_id': page_id, 'url': expected.get('url', url)}:
        failures.append('Incorrect source metadata.')
    if hashlib.sha256(url.encode('utf-8')).hexdigest() != page_id:
        failures.append('Source URL hash does not match page_id.')
    domain = urlsplit(url).hostname.encode('idna').decode('ascii').lower().rstrip('.')
    folder = domain.replace('.', '_')
    if actual['output'] != ['data/articles/' + folder + '/' + page_id + '.md']:
        return failures + ['Incorrect article output path.']
    if 'output' in expected and actual['output'][0] != expected['output']:
        failures.append('Unexpected domain folder output.')
    with (project / value['article_file']).open(encoding='utf-8', newline='') as source:
        article = source.read().rstrip('\r\n')
    lines = article.splitlines()
    if lines and (lines[-1].startswith('Source Page Id:') or lines[-1].startswith('Source Page ID:')):
        article = article[:article.rfind(lines[-1])].rstrip('\r\n')
    expected_content = article + '\n\nSource Page ID: ' + page_id + '\n\n' + os.environ['PROJECT_TRANSACTION_SIGNATURE_MARKDOWN']
    try:
        with (root / folder / (page_id + '.md')).open(encoding='utf-8', newline='') as saved:
            if saved.read() != expected_content:
                failures.append('Stored Markdown does not preserve the article with its canonical source label.')
    except OSError as exc:
        failures.append('Could not read article: ' + str(exc))
    return failures
