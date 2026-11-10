# Personal Assistive Intelligence (PAI) Search

PAI Search builds a local, searchable collection of web articles from URLs you
provide. It extracts article content, saves it as Markdown, and indexes it by
entity so you can ask questions across the collection and trace answers back to
the source articles.

## Use Cases

### Index a webpage

Give PAI Search a public article URL. It saves the extracted content as
Markdown and indexes it by entity for later searches.

### Search the personal index

Ask a question, request a summary, or compare topics across the pages you’ve
indexed. Answers cite the source articles.

### Publish search queries

Export saved search reports as Markdown under `data/queries/`. The publish task
commits and pushes those files to the remote repository.

## Project Setup

### System requirements

- PAI Search currently supports **macOS only**. Its tool and transaction
  runners use the macOS `sandbox_init` API.
- Use a Mac that meets the requirements for the ChatGPT desktop app.
  [OpenAI desktop app documentation](https://learn.chatgpt.com/docs/app)
- Use a local folder where you can write files. Internet access is needed to
  sign in to Codex, install Python packages, and fetch public webpages.

### ChatGPT account and plan

Sign in with a ChatGPT account. The Free plan can run Codex in the desktop app
where access has rolled out. Paid plans offer different usage limits and model
access. [Current Codex plans and limits](https://learn.chatgpt.com/docs/pricing)

### Install the desktop app on macOS

1. Download the macOS installer.
   [Official ChatGPT desktop app download](https://learn.chatgpt.com/docs/app)
2. Open the downloaded disk image and drag ChatGPT into **Applications**.
3. Open ChatGPT, sign in, and select **Codex** in the desktop app.

### Install system tools and get the project

1. Download the macOS installer for Python 3.11 or newer from
   [python.org](https://www.python.org/downloads/macos/). Open the downloaded
   `.pkg` and follow the installer prompts.
2. Run `git --version` if you need to clone the repository or publish results.
   If Git is unavailable, run `xcode-select --install` in Terminal and follow
   the prompts to install Apple's Command Line Tools.
3. Clone the repository to a local folder, or use your existing checkout.
   For publishing, use a checkout with a configured remote and credentials
   that allow pushes to it.

### Set up the project environments

Open the repository root, the folder containing this README, as a local
project in Codex. Use a checkout on a branch other than `main` for this
project-wide setup. Start a project chat and paste the prompt below so Codex
runs the environment setup from the repository root.

```text
Set up PAI Search from the repository root and follow AGENTS.md.

1. Run uname -s and confirm it returns Darwin. Run python3.11 --version.
   If Python 3.11 is unavailable, find a newer installed Python and verify
   its version. Use that executable in place of python3.11 below.
2. Create each missing environment using its corresponding command.
   python3.11 -m venv tools/.venv
   python3.11 -m venv transactions/.venv
   Reuse existing compatible environments. Report incompatible ones.
3. Install any missing extraction dependencies in the tools environment.
   tools/.venv/bin/python -m pip install 'trafilatura>=2.0,<3.0' lxml_html_clean
   Use only the standard library for transaction code.
4. Verify package consistency and check that both runner CLIs load.
   tools/.venv/bin/python -m pip check
   tools/.venv/bin/python -B tools/runner.py --help
   transactions/.venv/bin/python -B transactions/runner.py --help
5. Report the Python version, verification results, and blockers.
```

After Codex verifies both environments, use the starter messages below.

## How to Run/Execute the Use Cases

Open a project chat from the repository root and send the starter message for
the use case you want to run.

### Index a webpage

Open a new chat in the project and paste the starter message below.

> set the context to tasks sub-project, prepare the environment with all dependencies, load task-webpage-index and validate the environment if the task can be run. Name the chat thread as **Index**.

The starter message sets the chat context to the `tasks` sub-project and loads
the `task-webpage-index` instructions. The chat is then ready to accept an
article URL. Indexing begins when you send the URL.

Rename the chat to **Index** and reuse it for all future indexing tasks.

For example, send one of these messages with your own public article URL.

```
https://example.com/article
Index this webpage: https://example.com/article
Add https://example.com/article to my personal index.
```

> [!NOTE]
> **Include only one URL per message. You can send multiple messages in the same
> chat without waiting for each one to finish. The messages queue up, and the
> chat indexes their URLs one at a time in the order you sent them.**

The [indexing task](tasks/task-webpage-index/TASK.md) saves the article under
`data/articles/` and its entity indexes under `data/index/`. With authorization,
the task commits those files and pushes the commit to the remote Git repository.

### Search the personal index

Open a new chat in the project and paste the starter message below.

> set the context to skills sub-project, prepare the environment with all dependencies, load skill-webpage-search and validate the environment if the task can be run. Rename the chat thread as **Search**.

The starter message sets the chat context to the `skills` sub-project and loads
the `skill-webpage-search` instructions. The chat is then ready to search your
personal index when you send a query.

Rename the chat to **Search** and reuse it for future searches.

For example, send one of these messages using topics you’ve indexed.

```text
What have I saved about battery storage?
Summarize my saved articles on grid-scale energy storage.
Compare what my indexed articles say about lithium-ion and sodium-ion batteries.
```

> [!NOTE]
> **Search draws from webpages you’ve already indexed. Index relevant pages in
> Index chat before asking about a topic that isn’t in your collection yet.**

The [search skill](skills/skill-webpage-search/SKILL.md) looks for relevant entity
entries in `data/index/`. It follows those entries to the corresponding Markdown
articles in `data/articles/` and uses the article content to formulate the answer.

Inline citations point to the index files in `data/index/` that support individual
claims. The references section links to the source articles in `data/articles/`.
The skill also saves a Markdown search report for later publishing.

### Publish search queries

Open a new chat in the project and paste the starter message below.

> set the context to tasks sub-project and load task-webpage-search-publish. Rename the chat thread as **Publish**.

The starter message loads the publishing task instructions. Rename the chat to
**Publish chat** and reuse it whenever you want to publish saved search reports.
To run the task, send the following message.

```text
task-webpage-search-publish
```

> [!NOTE]
> **Run a search in Search chat first so there’s a saved report to publish.**

The [publish task](tasks/task-webpage-search-publish/TASK.md) exports saved search
reports as Markdown files under `data/queries/`, commits those files, and pushes
the commit to the remote Git repository. After a successful Git step, it cleans
up the corresponding local search inputs and outputs. The task reports which
files it exported, the push status, and the cleanup outcome.


