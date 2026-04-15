"""
Zep Memory Provider Plugin for Hermes Agent.

Integrates Zep's temporal knowledge graph and context engineering
platform as a persistent memory backend for Hermes Agent.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)


class ZepMemoryProvider(MemoryProvider):
    """Memory provider backed by Zep's context engineering platform.

    Zep builds a temporal knowledge graph from conversations and business
    data, providing rich, personalized context for every agent turn.
    """

    # ------------------------------------------------------------------
    # Core lifecycle
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "zep"

    def is_available(self) -> bool:
        """Return True when the API key is present. No network calls."""
        return bool(os.environ.get("ZEP_API_KEY"))

    def initialize(self, session_id: str, **kwargs) -> None:
        """Called once at agent startup."""
        self._api_key = os.environ.get("ZEP_API_KEY", "")
        self._session_id = session_id
        self._hermes_home = kwargs.get("hermes_home", "")
        self._sync_thread: threading.Thread | None = None
        self._last_context: str = ""

        # Load persisted config (non-secret fields)
        self._config = self._load_config()

        # Lazy-import so the plugin doesn't crash at discovery time
        # if zep-cloud isn't installed yet.
        try:
            from zep_cloud.client import Zep
        except ImportError:
            logger.error(
                "zep-cloud SDK not installed. Run: pip install zep-cloud"
            )
            raise

        self._client = Zep(api_key=self._api_key)

        self._user_id = self._config.get("user_id", "hermes-user")
        self._user_name = self._config.get("first_name", "Hermes")

        # Platform type from hermes kwargs (e.g. "discord", "telegram", "cli")
        self._platform = kwargs.get("platform", "").lower()

        # Ensure user exists in Zep
        self._ensure_user()

        # Build a deterministic thread ID from platform + chat context so the
        # same channel/DM always reuses the same Zep thread.
        # DM  → {platform}_user_{user_id}   e.g. discord_user_123456789
        # Group/Channel → {platform}_{chat_id}  e.g. discord_374456867646210050
        origin = self._resolve_session_origin(session_id)
        chat_type = origin.get("chat_type", "")
        chat_id = str(origin.get("chat_id", ""))
        origin_user_id = str(origin.get("user_id", ""))

        if self._platform and chat_type == "dm" and origin_user_id:
            self._thread_id = f"{self._platform}_user_{origin_user_id}"
        elif self._platform and chat_id:
            self._thread_id = f"{self._platform}_{chat_id}"
        else:
            logger.warning(
                "platform=%r chat_type=%r chat_id=%r — "
                "falling back to session-based thread ID",
                self._platform, chat_type, chat_id,
            )
            self._thread_id = f"hermes-{self._session_id}"
        self._ensure_thread()

        # Warm the user cache at startup (Zep best practice: warm when user
        # first connects, not on every turn).
        try:
            self._client.user.warm(user_id=self._user_id)
        except Exception:
            pass

        logger.info("Zep memory provider initialized (thread=%s)", self._thread_id)

    # ------------------------------------------------------------------
    # User / thread helpers
    # ------------------------------------------------------------------

    def _resolve_session_origin(self, session_id: str) -> dict:
        """Resolve the origin metadata for this session from the hermes session store.

        Returns the origin dict (with chat_id, chat_type, user_id, etc.)
        or empty dict if not found.
        """
        if not self._hermes_home:
            return {}
        sessions_file = Path(self._hermes_home) / "sessions" / "sessions.json"
        if not sessions_file.exists():
            return {}
        try:
            data = json.loads(sessions_file.read_text())
            for _key, entry in data.items():
                if entry.get("session_id") == session_id:
                    return entry.get("origin") or {}
            return {}
        except Exception as exc:
            logger.debug("Could not resolve origin from sessions.json: %s", exc)
            return {}

    def _ensure_user(self) -> None:
        """Create the Zep user if it doesn't already exist.

        Zep best practice: provide first_name, last_name, and email so the
        user node is correctly anchored in the knowledge graph.
        """
        try:
            self._client.user.get(user_id=self._user_id)
        except Exception:
            try:
                first = self._config.get("first_name", "Hermes")
                last = self._config.get("last_name", "User")
                email = self._config.get("email")
                kwargs = {
                    "user_id": self._user_id,
                    "first_name": first,
                    "last_name": last,
                }
                if email:
                    kwargs["email"] = email
                self._client.user.add(**kwargs)
                logger.info("Created Zep user: %s", self._user_id)
            except Exception as exc:
                logger.warning("Could not create Zep user: %s", exc)

    def _ensure_thread(self) -> None:
        """Create the Zep thread for this session if needed."""
        try:
            self._client.thread.create(
                thread_id=self._thread_id,
                user_id=self._user_id,
            )
            logger.info("Created Zep thread: %s", self._thread_id)
        except Exception:
            # Thread likely already exists
            pass

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def get_config_schema(self):
        return [
            {
                "key": "api_key",
                "description": "Zep API key",
                "secret": True,
                "required": True,
                "env_var": "ZEP_API_KEY",
                "url": "https://app.getzep.com/",
            },
            {
                "key": "user_id",
                "description": "Zep user ID for this Hermes profile",
                "default": "hermes-user",
            },
            {
                "key": "first_name",
                "description": "First name for the Zep user node",
                "default": "Hermes",
            },
            {
                "key": "last_name",
                "description": "Last name for the Zep user node",
                "default": "User",
            },
            {
                "key": "email",
                "description": "Email for the Zep user node (improves graph mapping)",
            },
        ]

    def save_config(self, values: dict, hermes_home: str) -> None:
        config_path = Path(hermes_home) / "zep.json"
        config_path.write_text(json.dumps(values, indent=2))

    def _load_config(self) -> dict:
        if not self._hermes_home:
            return {}
        config_path = Path(self._hermes_home) / "zep.json"
        if config_path.exists():
            try:
                return json.loads(config_path.read_text())
            except Exception:
                return {}
        return {}

    # ------------------------------------------------------------------
    # Tool schemas
    # ------------------------------------------------------------------

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "zep_search",
                    "description": (
                        "Search the Zep knowledge graph for facts, entities, "
                        "and prior conversation context relevant to a query."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query.",
                            },
                            "scope": {
                                "type": "string",
                                "enum": ["edges", "nodes"],
                                "description": "Search scope: 'edges' for facts/relationships, 'nodes' for entities.",
                                "default": "edges",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max results to return.",
                                "default": 10,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "zep_add",
                    "description": (
                        "Add arbitrary text or JSON data to the user's Zep "
                        "knowledge graph (e.g. notes, business data)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "data": {
                                "type": "string",
                                "description": "The data to add.",
                            },
                            "data_type": {
                                "type": "string",
                                "enum": ["text", "json"],
                                "description": "Type of data being added.",
                                "default": "text",
                            },
                        },
                        "required": ["data"],
                    },
                },
            },
        ]

    def handle_tool_call(self, name: str, args: dict) -> str:
        if name == "zep_search":
            return self._handle_search(args)
        elif name == "zep_add":
            return self._handle_add(args)
        return json.dumps({"error": f"Unknown tool: {name}"})

    def _handle_search(self, args: dict) -> str:
        query = args.get("query", "")
        scope = args.get("scope", "edges")
        limit = args.get("limit", 10)
        try:
            results = self._client.graph.search(
                user_id=self._user_id,
                query=query,
                scope=scope,
                limit=limit,
                reranker="cross_encoder",
            )
            if scope == "edges" and results.edges:
                facts = []
                for edge in results.edges:
                    valid = getattr(edge, "valid_at", None) or "unknown"
                    invalid = getattr(edge, "invalid_at", None) or "present"
                    facts.append(
                        f"- {edge.fact} (valid: {valid} – {invalid})"
                    )
                return "\n".join(facts) if facts else "No facts found."
            elif scope == "nodes" and results.nodes:
                nodes = []
                for node in results.nodes:
                    summary = getattr(node, "summary", "") or ""
                    nodes.append(f"- {node.name}: {summary[:200]}")
                return "\n".join(nodes) if nodes else "No entities found."
            return "No results found."
        except Exception as exc:
            logger.warning("Zep search failed: %s", exc)
            return json.dumps({"error": str(exc)})

    def _handle_add(self, args: dict) -> str:
        data = args.get("data", "")
        data_type = args.get("data_type", "text")
        try:
            self._client.graph.add(
                user_id=self._user_id,
                type=data_type,
                data=data,
            )
            return "Data added to Zep knowledge graph."
        except Exception as exc:
            logger.warning("Zep add failed: %s", exc)
            return json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------

    def system_prompt_block(self) -> str:
        """Return a static block describing the Zep memory provider."""
        return (
            "[ZEP MEMORY] You have access to a persistent knowledge graph "
            "powered by Zep. Use the zep_search tool to recall facts from "
            "prior conversations and the zep_add tool to store important "
            "information. Context from the knowledge graph is automatically "
            "prefetched each turn."
        )

    def prefetch(self, query: str) -> str:
        """Retrieve Zep context block before each API call.

        If the last sync_turn already returned a context block via
        return_context=True, we use that cached value to avoid a
        redundant round-trip.  Otherwise we fall back to an explicit call.
        """
        # Use cached context from the last sync_turn if available
        if self._last_context:
            ctx = self._last_context
            self._last_context = ""
            return ctx
        try:
            result = self._client.thread.get_user_context(
                thread_id=self._thread_id
            )
            return result.context or ""
        except Exception as exc:
            logger.debug("Zep prefetch failed: %s", exc)
            return ""

    def queue_prefetch(self, query: str) -> None:
        """No-op. Cache warming happens once at initialize(), not every turn.

        Zep best practice: warm the cache when the user first connects
        (done in initialize), not repeatedly between turns.
        """
        pass

    def sync_turn(self, user_content: str, assistant_content: str, **kwargs) -> None:
        """Persist the conversation turn to Zep. Must be non-blocking.

        Zep best practices applied:
        - name field set on both messages for correct graph construction
        - created_at timestamps in RFC3339 for temporal accuracy
        - return_context=True to get the context block in the same call
          (avoids a separate get_user_context round-trip on next prefetch)
        - ignore_roles=["assistant"] so assistant messages are stored in
          thread history but don't create graph nodes/edges
        """
        def _sync():
            try:
                from zep_cloud.types import Message

                messages = [
                    Message(
                        role="user",
                        name=self._user_name,
                        content=user_content,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    ),
                    Message(
                        role="assistant",
                        name="Hermes",
                        content=assistant_content,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    ),
                ]
                response = self._client.thread.add_messages(
                    self._thread_id,
                    messages=messages,
                    return_context=True,
                    ignore_roles=["assistant"],
                )
                # Cache the context block so the next prefetch() can use it
                # without an extra API call.
                if response and hasattr(response, "context") and response.context:
                    self._last_context = response.context
            except Exception as exc:
                logger.warning("Zep sync_turn failed: %s", exc)

        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)
        self._sync_thread = threading.Thread(target=_sync, daemon=True)
        self._sync_thread.start()

    def on_session_end(self, messages: list) -> None:
        """Flush any pending sync on session end."""
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=10.0)
        logger.info("Zep session ended for thread %s", self._thread_id)

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror built-in MEMORY.md writes to Zep as text episodes."""
        try:
            self._client.graph.add(
                user_id=self._user_id,
                type="text",
                data=f"[{action}] {target}: {content}",
            )
        except Exception as exc:
            logger.debug("Zep on_memory_write failed: %s", exc)

    def shutdown(self) -> None:
        """Clean up on process exit."""
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)
        logger.info("Zep memory provider shut down.")


# ------------------------------------------------------------------
# Plugin entry point
# ------------------------------------------------------------------

def register(ctx) -> None:
    """Called by the Hermes memory plugin discovery system."""
    ctx.register_memory_provider(ZepMemoryProvider())
