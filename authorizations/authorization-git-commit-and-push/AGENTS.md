# authorization-git-commit-and-push

Follow [policy](../AGENTS.md) and [definition](AUTHORIZATION.md). Only tasks execute
this authorisation through the shared runner. Never run Git, call the Git component
or dispatch effects here. authorization.py owns fixed permission terms; do not
resolve scope or lifetime from runtime arguments or current Git settings.

Return the canonical .runtime/grant.md path. On a cache miss the task presents that
complete pending Markdown request, obtains explicit human consent and resumes with
the exact request ID/token and decision reference. Do not prompt on same-session
active reuse. Reject other sessions until expiry/revocation; pending reservations
expire after 15 minutes. Approval grants all defined permissions or none.

Revoke only on an explicit human request coordinated by a task. Preserve approved
terms when updating status. Consumers read the file independently and never call
this component, its adapter or the framework during execution.
