# Zep Memory Provider

Persistent, cross-session memory powered by [Zep](https://www.getzep.com) — a context engineering platform that builds temporal knowledge graphs from conversations and business data.

## What it does

- Persists every conversation turn to Zep's knowledge graph via `sync_turn`
- Prefetches a context block (user summary + relevant facts) before each agent response
- Exposes `zep_search` and `zep_add` tools so the agent can query and write to the graph
- Mirrors built-in `MEMORY.md` writes to Zep for unified knowledge
- Warms the Zep user cache between turns for low-latency retrieval

## Setup

1. Install the Zep Python SDK:

   ```bash
   pip install zep-cloud
   ```

2. Run the Hermes memory setup wizard:

   ```bash
   hermes memory setup
   ```

   You'll be prompted for your Zep API key (get one at https://app.getzep.com).

3. Optionally configure `user_id`, `first_name`, and `last_name` in `$HERMES_HOME/zep.json`.

## Config

| Key          | Description                          | Default        |
|-------------|--------------------------------------|----------------|
| `api_key`   | Zep API key (stored in `.env`)       | —              |
| `user_id`   | Zep user ID for this profile         | `hermes-user`  |
| `first_name`| First name on the Zep user node      | `Hermes`       |
| `last_name` | Last name on the Zep user node       | `User`         |

## Tools

| Tool         | Description                                                    |
|-------------|----------------------------------------------------------------|
| `zep_search`| Search the knowledge graph for facts or entities               |
| `zep_add`   | Add text or JSON data directly to the user's knowledge graph   |

## CLI commands

When Zep is the active provider:

```bash
hermes zep status   # Check connection and user info
hermes zep config   # Print current config
hermes zep search "query"  # Search the knowledge graph
```

## How it works

Zep automatically extracts entities, relationships, and facts from conversations, building a temporal knowledge graph per user. The `prefetch` hook calls `thread.get_user_context()` each turn, which returns a context block containing a user summary and the most relevant facts — ready to inject into the system prompt. Facts include temporal validity ranges so the agent can reason about what's current vs. outdated.

For more details, see the [Zep documentation](https://help.getzep.com).
