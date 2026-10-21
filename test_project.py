"""Check project contracts and isolated regressions without changing dependencies."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def check_contracts():
    spec = importlib.util.spec_from_file_location('tool_contract_runner', ROOT / 'tools' / 'runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.verify_environment()
    tools = sorted((ROOT / 'tools').glob('tool-*'))
    forms = sorted((ROOT / 'forms').glob('form-*'))
    skills = sorted((ROOT / 'skills').glob('skill-*'))
    tasks = sorted((ROOT / 'tasks').glob('task-*'))
    for tool in tools:
        runner.resolve_tool(tool.name)  # Inspects source; never imports tool implementations.
    for folder in forms + skills:
        prefix = 'form' if folder in forms else 'skill'
        if folder.is_symlink() or not folder.is_dir() or len(folder.name) >= 64 or not re.fullmatch(prefix + r'-[a-z0-9]+(?:-[a-z0-9]+)*', folder.name):
            raise ValueError(f'Invalid {prefix} directory: {folder.name}')
        required = ('AGENTS.md', 'form.html', 'form.js', 'form.css') if prefix == 'form' else ('AGENTS.md', 'SKILL.md')
        for name in required:
            path = folder / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Missing regular file: {folder.name}/{name}')
        if prefix == 'skill':
            entry = (folder / 'SKILL.md').read_text()
            frontmatter = re.match(r'\A---\n(.*?)\n---\n', entry, re.S)
            if (not frontmatter or not re.search(r'^name: ' + re.escape(folder.name) + r'\s*$', frontmatter[1], re.M)
                    or not re.search(r'^description: \S.+$', frontmatter[1], re.M)
                    or '[AGENTS.md](AGENTS.md)' not in entry):
                raise ValueError(f'Invalid skill discovery contract: {folder.name}')
    sections = ('Purpose and scope', 'Inputs and outputs', 'Execution procedure',
                'Workflow diagram', 'Recovery and cancellation', 'Acceptance criteria')
    for task in tasks:
        if task.is_symlink() or not task.is_dir() or len(task.name) >= 64 or not re.fullmatch(r'task-[a-z0-9]+(?:-[a-z0-9]+)*', task.name):
            raise ValueError(f'Invalid task directory: {task.name}')
        for name in ('TASK.md', 'AGENTS.md'):
            path = task / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Missing regular file: {task.name}/{name}')
        entry = (task / 'TASK.md').read_text()
        instructions = (task / 'AGENTS.md').read_text()
        if not entry.startswith(f'# {task.name}\n') or '](AGENTS.md)' not in entry:
            raise ValueError(f'Invalid task discovery contract: {task.name}')
        for section in sections:
            if f'\n## {section}\n' not in instructions:
                raise ValueError(f'Missing task section {section}: {task.name}')
    for path in (ROOT / 'tasks').rglob('*.md'):
        if any(part in {'checkpoints', 'runs', 'output', 'logs'} for part in path.relative_to(ROOT / 'tasks').parts):
            continue
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if '://' in target or target.startswith('#'):
                continue
            if not (path.parent / target.split('#', 1)[0]).is_file():
                raise ValueError(f'Broken task link in {path.relative_to(ROOT)}: {target}')
    print(f'Contracts: {len(tools)} tools, {len(forms)} forms, {len(skills)} skills, {len(tasks)} tasks', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sandbox', action='store_true', help='Also test macOS worker isolation using a disposable tool')
    args = parser.parse_args()
    try:
        check_contracts()
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    suites = [('tools', ['test_runner.py']),
              ('forms', ['-m', 'unittest', '-q', 'test_store.py', 'test_journal.py', 'test_http.py'])]
    if args.sandbox:
        suites.append(('tools', ['-m', 'unittest', '-q',
                                'test_output_sandbox.OutputSandboxTests.test_worker_write_and_read_boundaries']))
    for directory, arguments in suites:
        print(f'Checking {directory}: {arguments[-1]}', flush=True)
        result = subprocess.run([sys.executable, '-B', *arguments], cwd=ROOT / directory, timeout=120)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
