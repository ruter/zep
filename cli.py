"""CLI subcommands for the Zep memory provider.

Registered automatically when Zep is the active memory provider.
Usage: hermes zep <subcommand>
"""

import json
import os
from pathlib import Path


def _get_client():
    from zep_cloud.client import Zep

    api_key = os.environ.get("ZEP_API_KEY", "")
    if not api_key:
        print("ZEP_API_KEY is not set.")
        return None
    return Zep(api_key=api_key)


def _get_config():
    from hermes_constants import get_hermes_home

    config_path = Path(get_hermes_home()) / "zep.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def zep_command(args):
    sub = getattr(args, "zep_command", None)

    if sub == "status":
        client = _get_client()
        if client is None:
            return
        config = _get_config()
        user_id = config.get("user_id", "hermes-user")
        try:
            user = client.user.get(user_id=user_id)
            print(f"Zep provider is active.")
            print(f"  User ID : {user.user_id}")
            print(f"  Created : {user.created_at}")
        except Exception as exc:
            print(f"Could not reach Zep: {exc}")

    elif sub == "config":
        config = _get_config()
        if config:
            print(json.dumps(config, indent=2))
        else:
            print("No Zep config found. Run `hermes memory setup` first.")

    elif sub == "search":
        query = getattr(args, "query", None)
        if not query:
            print("Usage: hermes zep search <query>")
            return
        client = _get_client()
        if client is None:
            return
        config = _get_config()
        user_id = config.get("user_id", "hermes-user")
        try:
            results = client.graph.search(
                user_id=user_id, query=query, scope="edges", limit=10
            )
            if results.edges:
                for edge in results.edges:
                    print(f"- {edge.fact}")
            else:
                print("No results found.")
        except Exception as exc:
            print(f"Search failed: {exc}")

    else:
        print("Usage: hermes zep <status|config|search>")


def register_cli(subparser) -> None:
    """Build the `hermes zep` argparse tree."""
    subs = subparser.add_subparsers(dest="zep_command")
    subs.add_parser("status", help="Show Zep provider status")
    subs.add_parser("config", help="Show current Zep config")
    search_parser = subs.add_parser("search", help="Search the Zep knowledge graph")
    search_parser.add_argument("query", nargs="?", help="Search query")
    subparser.set_defaults(func=zep_command)
