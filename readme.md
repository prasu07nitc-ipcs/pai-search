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
project in Codex. Start a project chat and paste the prompt below so Codex
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
5. If this checkout will be used for publishing, check the paired data branch.
   transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '{"check_only":true}'
   If the remote branch is missing, tell me its name and remote so I can create
   it manually. Report remote access errors separately.
6. Report the Python version, verification results, and blockers.
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
`data/articles/` and its entity indexes under `data/index/`. Use the Index choice in the Publish chat to publish those files.

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

> set the context to tasks sub-project and load task-webpage-publish. Run its read-only paired data branch check and report whether Publish is ready. Rename the chat thread as **Publish**.

The starter message loads the publishing task instructions. Rename the chat to
**Publish** and reuse it to publish saved search reports or webpage indices.
To run the task, send the following message.

```text
task-webpage-publish
```

> [!NOTE]
> **Prepare content in the Search or Index chat before publishing it.**

The [publish task](tasks/task-webpage-publish/TASK.md) ends its turn with a
prompt. Select **Search**, **Index**, or **Skip** in the control, or send the
choice as your next chat message. Skip
cancels the invocation. Search exports saved reports to `data/queries/`. Index
uses locally saved articles and entity index files. The task commits and pushes
the selected files to the working branch's existing paired `data-<branch>` and
cleans up corresponding source artifacts after remote verification.

## What to Expect After a Successful Run

### Index — Article ready to search

The Index chat reports the page ID and the number of entity index files it
saved. It links to the saved Markdown article and its extracted context. The
article in `data/articles/` and its entity entries in `data/index/` are ready
for local searches and for the **Index** option in Publish.

#### Worked example

Use the saved [Personal Assistive Intelligence article](https://www.linkedin.com/pulse/personal-assistive-intelligence-portable-networked-sushant-pradhan-rcoqf)
from LinkedIn. Its page ID is:

```text
19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198
```

The URL's hostname, `www.linkedin.com`, becomes the folder
`www_linkedin_com`. The saved example has one article file and 16 entity files.
Here are the article and two of the entity files:

```text
data/articles/www_linkedin_com/19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
data/index/www_linkedin_com/portability/19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
data/index/www_linkedin_com/networkability/19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
```

The same three files shown as a directory tree:

```text
data/
├── articles/
│   └── www_linkedin_com/
│       └── 19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
└── index/
    └── www_linkedin_com/
        ├── networkability/
        │   └── 19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
        └── portability/
            └── 19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
```

The **article file** holds the extracted article. The metadata at the bottom
records the URL submitted to Index and the page ID used in the filename. These
are selected lines from the saved file:

```markdown
## Title

Personal Assistive Intelligence: Personal, Portable, and Networked

<!-- Article body and other metadata omitted from this example. -->

## Meta Data

- **requested_url:** https://www.linkedin.com/pulse/personal-assistive-intelligence-portable-networked-sushant-pradhan-rcoqf
- **page_id:** 19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198
```

An **entity file** holds the passages indexed under that topic. The
`portability` folder contains this page's Portability entry. Here is its
first block, with the passage shortened for this example:

```markdown
# Portability

## Sequence: **4/16**
- Utterance: Portability carries accumulated knowledge, preferences, methods, and decision principles across tasks, domains, tools, and platforms. […]
- Entity Category: Concept
- Indexed At: 2026-11-10T19:06:10.185059+05:30
- Last Validated At: 2026-10-31T02:28:33+00:00
```

`4/16` means this passage was fourth among the 16 passages indexed for the
whole article. `Concept` is the category assigned to the passage.
`Indexed At` records when Index wrote the entry, and `Last Validated At`
comes from the article's recorded modification date. If several passages
cover the same entity, they appear as separate blocks in its file.

#### Verify the page ID and files

The page ID is the SHA-256 hash of the exact requested URL. Anyone hashing
that same URL text gets the same ID on any machine. The ID is practically
unique to that URL because SHA-256 collisions are extraordinarily unlikely.
A change to the URL text, such as adding a trailing slash, changes the ID
even if the browser opens the same article.

Run these commands from the repository root:

```sh
url='https://www.linkedin.com/pulse/personal-assistive-intelligence-portable-networked-sushant-pradhan-rcoqf'
page_id=$(printf '%s' "$url" | shasum -a 256 | cut -d ' ' -f 1)
printf '%s\n' "$page_id"
ls "data/articles/www_linkedin_com/$page_id.md"
find data/index/www_linkedin_com -type f -name "$page_id.md" -print
```

Compare the printed ID with the ID above and in the article footer. The
`ls` command should show one article file, and `find` should list 16 paths
for this saved example. When checking another run, compare the number of
matching paths with the entity file count in the Index chat. A run with
zero entity files saves just the article.

### Search — Answer and saved report

#### Worked example

After indexing the LinkedIn article above, ask the **Search** chat:

> What does my saved article say about portability?

The chat might answer that portability lets an assistant carry useful
knowledge, preferences, and decision principles across tasks and platforms.
The inline **Portability** citation opens the entity file containing the
supporting passage. The **References** section links the article title to the
full saved article.

#### Find and read the saved report

Search saves a Markdown report under the search skill's `output/` folder.
The filename uses the query's run ID. The article's page ID still appears
in the filenames that the response cites.

```text
skills/
└── skill-webpage-search/
    └── output/
        └── 816107f59c74057aa083108182a3e3267294ae2c7e86141533755a4694023b11.md
```

This example shows the report layout. The timestamp is illustrative and the
links use repository-relative paths for readability. Search writes absolute
paths in the actual report.

```markdown
# Query
What does my saved article say about portability?

# Response
Portability lets an assistant carry useful knowledge, preferences, and decision principles across tasks and platforms. [Portability](data/index/www_linkedin_com/portability/19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md)

## References
- [Personal Assistive Intelligence: Personal, Portable, and Networked](data/articles/www_linkedin_com/19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md)

# Index Files Analysed
- [data/index/www_linkedin_com/portability/19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md](data/index/www_linkedin_com/portability/19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md)

# Execution time
2026-11-10T14:00:00+00:00

# Query ID
816107f59c74057aa083108182a3e3267294ae2c7e86141533755a4694023b11
```

**Response** contains what you see in the chat. **Index Files Analysed**
also records files Search reviewed but did not cite. **Execution time**
records when the run started in UTC. **Query ID** matches the report filename.

#### Verify the answer and report

1. Open the inline citation in the Search chat and check that its passage
   supports the answer. Then open the article under **References** to read
   the passage in context.
2. Open the report in `skills/skill-webpage-search/output/`. Check that
   **Query** matches what you sent, **Response** matches the chat answer, and
   **Query ID** matches the filename.
3. Use **Search** in Publish to export the saved report to `data/queries/`.

If no indexed article supports the query, Search reports that outcome in
the chat and saves it in the Markdown report.

### Publish — Files verified on the remote branch

#### Worked example

In the **Publish** chat, run `task-webpage-publish` and select **Index** to
publish the LinkedIn article and its entity files. Run the task again and
select **Search** to publish the saved report about portability. Each choice
publishes a batch, so the remote can also receive other prepared files of
the selected type.

Publish uses the existing paired branch. For example, if the working branch
is `main`, look for the files on `data-main` in the remote repository. After
both choices complete, the remote branch can contain these files from the
worked example. The tree shows two of the article's 16 entity files.

```text
data/
├── articles/
│   └── www_linkedin_com/
│       └── 19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
├── index/
│   └── www_linkedin_com/
│       ├── networkability/
│       │   └── 19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
│       └── portability/
│           └── 19bbd9e1748883815cecde97c674608cf4356380f5b7e7a81d2edd3dc3e6e198.md
└── queries/
    └── 816107f59c74057aa083108182a3e3267294ae2c7e86141533755a4694023b11.md
```

The article and entity files keep their page ID and Markdown contents.
The query file keeps the report's query ID and contains the query, response,
reviewed index files, execution time, and query ID shown in the Search example.

#### Verify the files on the remote

1. In the Publish chat, check the selected type, batch IDs, verified file
   links, remote, branch, and commit ID. The status tells you whether Publish
   pushed a change or verified that the remote already had the files.
2. Open the remote repository and switch to the branch named in the chat.
   For **Index**, open the article and a corresponding entity file. Check
   that the two filenames share the page ID. For **Search**, open the file
   in `data/queries/` and check that the **Query ID** at the bottom matches
   the filename and **Query** contains the portability question.
3. Check the cleanup summary in the Publish chat. After remote verification,
   Publish can remove eligible intermediate files from Index or the local
   search report that it exported. The summary reports what was removed
   and any cleanup still pending.
