"""Answer a question using a Notion page as Claude's project-knowledge context.

Fetches a Notion page's block tree (recursing into nested blocks), renders it to
basic Markdown, and passes it to Claude as grounding context for a user prompt.

Config comes from CLI flags, falling back to environment variables:

    NOTION_TOKEN        Notion integration token          (required)
    ANTHROPIC_API_KEY   Anthropic API key                 (required unless an
                                                           `ant auth login` profile exists)
    NOTION_PAGE_ID      default for --page-id
    NOTION_QUERY        default for --query

Example:
    python scripts/notion_claude_sync.py \\
        --page-id 1a2b3c4d... \\
        --query "What are the core deliverables?"
"""

import argparse
import os
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional; env vars can be set directly.
    def load_dotenv(*_args, **_kwargs):
        return False

from notion_client import Client
from notion_client.errors import APIResponseError
import anthropic

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_QUERY = "What are the core deliverables mentioned in our project documentation?"

HEADING_PREFIX = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### "}
LIST_PREFIX = {"bulleted_list_item": "- ", "numbered_list_item": "1. ", "to_do": "- [ ] "}
# Block types whose text is rendered as a plain paragraph.
PLAIN_TYPES = {"paragraph", "quote", "callout", "toggle"}


def _rich_text(block: dict, block_type: str) -> str:
    """Concatenate the plain_text of a block's rich_text array."""
    objects = block.get(block_type, {}).get("rich_text", [])
    return "".join(obj.get("plain_text", "") for obj in objects)


def _iter_children(notion: Client, block_id: str):
    """Yield every child block of block_id, following pagination."""
    kwargs = {"block_id": block_id}
    while True:
        resp = notion.blocks.children.list(**kwargs)
        yield from resp.get("results", [])
        if not resp.get("has_more"):
            return
        kwargs["start_cursor"] = resp.get("next_cursor")


def render_block_tree(notion: Client, block_id: str, depth: int = 0) -> list[str]:
    """Recursively render a Notion block subtree into Markdown lines."""
    lines: list[str] = []
    indent = "    " * depth
    for block in _iter_children(notion, block_id):
        block_type = block.get("type", "")
        text = _rich_text(block, block_type)

        if block_type in HEADING_PREFIX and text:
            lines.append(f"{indent}{HEADING_PREFIX[block_type]}{text}")
        elif block_type in LIST_PREFIX and text:
            prefix = LIST_PREFIX[block_type]
            if block_type == "to_do" and block.get("to_do", {}).get("checked"):
                prefix = "- [x] "
            lines.append(f"{indent}{prefix}{text}")
        elif block_type == "code" and text:
            lang = block.get("code", {}).get("language", "")
            lines.append(f"{indent}```{lang}\n{text}\n{indent}```")
        elif block_type in PLAIN_TYPES and text:
            lines.append(f"{indent}{text}")
        elif block_type == "divider":
            lines.append(f"{indent}---")

        if block.get("has_children"):
            lines.extend(render_block_tree(notion, block["id"], depth + 1))
    return lines


def fetch_notion_page_text(notion: Client, page_id: str) -> str:
    """Fetch a Notion page's full block tree as basic Markdown."""
    return "\n\n".join(render_block_tree(notion, page_id))


def query_claude_with_notion_knowledge(
    notion: Client,
    anthropic_client: anthropic.Anthropic,
    notion_page_id: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    print("Fetching fresh knowledge context from Notion...", file=sys.stderr)
    knowledge_context = fetch_notion_page_text(notion, notion_page_id)
    if not knowledge_context.strip():
        raise SystemExit(
            f"No readable content found on Notion page {notion_page_id}. "
            "Check the page ID and that the integration has access to it."
        )

    system_instruction = (
        "You are an expert project assistant. Use the following Project Knowledge "
        "to answer the user's prompt. If the answer cannot be found in the knowledge "
        "base, state that you do not know.\n\n"
        f"<project_knowledge>\n{knowledge_context}\n</project_knowledge>"
    )

    print(f"Querying {model} with updated context...", file=sys.stderr)
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_instruction,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--page-id",
        default=os.environ.get("NOTION_PAGE_ID"),
        help="Notion page ID to pull knowledge from (env: NOTION_PAGE_ID).",
    )
    parser.add_argument(
        "--query",
        default=os.environ.get("NOTION_QUERY", DEFAULT_QUERY),
        help="Question to ask Claude (env: NOTION_QUERY).",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model ID (default: {DEFAULT_MODEL}).")
    parser.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help=f"Response token cap (default: {DEFAULT_MAX_TOKENS})."
    )
    args = parser.parse_args(argv)
    if not args.page_id:
        parser.error("a Notion page ID is required (pass --page-id or set NOTION_PAGE_ID)")
    return args


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # Reads variables from a .env file in the working directory, if present.
    args = parse_args(argv)

    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print("Set the NOTION_TOKEN environment variable.", file=sys.stderr)
        return 2

    notion = Client(auth=notion_token)
    # anthropic.Anthropic() also resolves ANTHROPIC_API_KEY / an `ant auth login` profile.
    anthropic_client = anthropic.Anthropic()

    try:
        answer = query_claude_with_notion_knowledge(
            notion, anthropic_client, args.page_id, args.query, args.model, args.max_tokens
        )
    except APIResponseError as exc:
        print(f"Notion API error: {exc}", file=sys.stderr)
        return 1
    except anthropic.APIError as exc:
        print(f"Anthropic API error: {exc}", file=sys.stderr)
        return 1

    print("\n--- Claude's Response ---")
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
