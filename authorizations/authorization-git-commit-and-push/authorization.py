"""Fixed development-time permission definition. No Git or consumer callbacks."""
# Edit these terms only during development. Runtime accepts no term overrides.
TERMS = {
    'Duration seconds': 86400,
    'Consumer': 'data/tx-commit-and-push',
    'Operation': 'commit-and-push',
    'Branch': 'data-test',
    'Remote URL': 'git@github.com:prasu07nitc-ipcs/pai-search.git',
    'Author name': 'pai-search-agent',
    'Author email': 'psa@sayujai.com',
    'Create branch': False,
    'Base commit': None,
    'Page scope': 'all',
    'Allowed roots': ['bookmark', 'index', 'articles'],
    'Message prefix': 'data: index webpage ',
    'Reuse': 'same-session-until-expiry',
}


def definition(project):
    return dict(TERMS)
