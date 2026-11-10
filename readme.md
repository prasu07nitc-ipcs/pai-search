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

## How to Run/Execute the Use Cases

Open a project chat from the repository root and send the starter message for
the use case you want to run.

### Index a webpage

Open a new chat in the project and paste the starter message below.

> set the context to tasks sub-project and load task-webpage-index. Name the chat thread as **Index**.

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

> set the context to skills sub-project and load skill-webpage-search. Rename the chat thread as **Search**.

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
> **Run a search in Search chat first so there’s a saved report to publish.
> Publishing requires authorization to commit and push the exported reports.**

The [publish task](tasks/task-webpage-search-publish/TASK.md) exports saved search
reports as Markdown files under `data/queries/`, commits those files, and pushes
the commit to the remote Git repository. After a successful Git step, it cleans
up the corresponding local search inputs and outputs. The task reports which
files it exported, the push status, and the cleanup outcome.


