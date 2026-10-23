# Task flowchart

Composite boxes group parallel stages. Both extractions must succeed before either
skill starts; both skills must succeed before any transaction starts; all three
transactions must succeed before publication. Edges show data wiring, not permission
to bypass these group barriers. The orchestrator retains page_id and source paths.

```mermaid
flowchart TD
    A[Task input] -->|input_text| V[tool-url-validate]

    subgraph EX["Parallel extraction · complete both before skills"]
        M[tool-webpage-metadata]
        D[tool-webpage-markdown]
    end
    subgraph SK["Parallel skills · complete both before transactions"]
        C[skill-context-encoder]
        W[skill-article-writer]
    end
    subgraph TX["Parallel transactions · complete all before publication"]
        BM[tx-bookmark]
        IX[tx-index]
        SA[tx-save-article]
    end

    V -->|url + page_id| M
    V -->|url + page_id| D
    D -->|Markdown text + retained page_id| C
    D -->|Markdown text| W
    M -->|metadata JSON + retained page_id| W
    M -->|page_id + metadata path| BM
    M -->|page_id + metadata path| IX
    M -->|page_id + metadata path| SA
    C -->|context JSON path| IX
    W -->|article Markdown path| SA
    BM -->|bookmark + meta paths| P[Publish output map and execution log]
    IX -->|utterances + meta paths per entity| P
    SA -->|article + meta paths| P
    P --> OK[Completed]

    V -->|Failure| R[Report error and supplied remedy]
    EX -->|Any failure| R
    SK -->|Any failure| R
    TX -->|Any failure| R
    P -->|Failure| R
    R --> T([Terminated])
```

Initialize the checkpoint before validation. Orchestration errors also reach error
reporting and termination. Failure paths include recording the failed attempt and
reconciling already-running work before the terminal response, per
[Failure termination](AGENTS.md#failure-termination). They never rejoin the success path.
Skills receive source contents; transactions receive file paths, with unused paths null.

The report forwards component errors/correction requests and any supplied remedy.
When none is supplied, state that rather than diagnosing the content. See the
[exact input wiring](AGENTS.md#2-wire-inputs) for field names and unused null paths.
