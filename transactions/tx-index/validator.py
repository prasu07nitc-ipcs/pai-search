"""Read-only index contract validation."""
import json
import os
from pathlib import Path
from datetime import datetime


def check_result(value: dict, actual: dict, expected: dict) -> list[str]:
    failures = []
    if actual['input'] != {'raw_input': value['raw_input'], 'processed_input': {
            'page_file': value['page_file'], 'context_file': value['context_file']}}:
        failures.append('Input changed.')
    root = Path(os.environ['PROJECT_TRANSACTION_DATA_DIRECTORY'])
    if actual['status'] == 'error':
        if actual['output'] is not None:
            failures.append('Failed output must be null.')
        if actual['error']['code'] != expected.get('error_code', actual['error']['code']):
            failures.append('Unexpected error code.')
        if list(root.iterdir()):
            failures.append('Validation failure wrote index artifacts.')
        return failures
    source = Path(os.environ['PROJECT_TRANSACTION_INPUT_ROOT'])
    contexts = json.loads((source / value['context_file']).read_text())
    page = json.loads((source / value['page_file']).read_text())
    groups = {}
    for item in contexts:
        groups.setdefault(item['entity_name'], []).append(item)
    from urllib.parse import urlsplit
    domain = urlsplit(page['url']).hostname.encode('idna').decode().lower().rstrip('.').replace('.', '_')
    expected_paths = [f'data/index/{folder}/{domain}/{page["page_id"]}.md' for folder in groups]
    if actual['output'] != expected_paths:
        failures.append('Incorrect affected paths or ordering.')
    for output in actual['output']:
        text = (root / Path(output).relative_to('data/index')).read_text()
        if not text.endswith('\n\n' + os.environ['PROJECT_TRANSACTION_SIGNATURE_MARKDOWN']):
            failures.append('Source signature does not match runner snapshot.')
        folder = Path(output).parts[2]
        for item in groups.get(folder, []):
            if f"Sequence: {item['seq_number']}/{len(contexts)}" not in text:
                failures.append('Missing original sequence fraction.')
            utterance = item['entity_utternace'].replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\n    ')
            if 'Utterance: ' + utterance not in text:
                failures.append('Utterance text changed.')
        if '## Source Page ID: ' + page['page_id'] not in text:
            failures.append('Missing source header.')
        if 'Indexed At: ' + actual['meta_data']['indexed_at'] not in text:
            failures.append('Missing execution timestamp.')
        if 'Last Validated At: ' + actual['meta_data']['last_validated_at'] not in text:
            failures.append('Missing validation timestamp.')
    for field in ('indexed_at', 'last_validated_at'):
        if datetime.fromisoformat(actual['meta_data'][field]).tzinfo is None:
            failures.append('Missing timezone.')
    if actual['meta_data']['total_utterances'] != len(contexts):
        failures.append('Incorrect total.')
    return failures
