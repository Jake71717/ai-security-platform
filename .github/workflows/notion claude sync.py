import os
from dotenv import load_dotenv
from notion_client import Client
from anthropic import Anthropic

load_dotenv()  # Reads variables from a .env file in the same directory, if present

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not NOTION_TOKEN or not ANTHROPIC_API_KEY:
    raise EnvironmentError("Set NOTION_TOKEN and ANTHROPIC_API_KEY environment variables.")

notion = Client(auth=NOTION_TOKEN)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

HEADING_PREFIX = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### "}
LIST_TYPES = {"bulleted_list_item": "- ", "numbered_list_item": "1. "}

def fetch_notion_page_text(page_id: str) -> str:
    """Fetches all blocks from a Notion page (paginated) into basic Markdown."""
    markdown_content = []
    cursor = None
    while True:
        resp = notion.blocks.children.list(block_id=page_id, start_cursor=cursor)
        for block in resp.get("results", []):
            block_type = block.get("type")
            rich_text_key = block_type
            text_objects = block.get(rich_text_key, {}).get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in text_objects)
            if not text:
                continue
            if block_type in HEADING_PREFIX:
                markdown_content.append(f"{HEADING_PREFIX[block_type]}{text}")
            elif block_type in LIST_TYPES:
                markdown_content.append(f"{LIST_TYPES[block_type]}{text}")
            elif block_type == "paragraph":
                markdown_content.append(text)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return "\n\n".join(markdown_content)

def query_claude_with_notion_knowledge(notion_page_id: str, user_prompt: str):
    print("Fetching fresh knowledge context from Notion...")
    knowledge_context = fetch_notion_page_text(notion_page_id)

    system_instruction = f"""You are an expert project assistant. Use the following uploaded Project Knowledge to answer the user's prompt.
If the answer cannot be found in the knowledge base, state that you do not know.

<project_knowledge>
{knowledge_context}
</project_knowledge>"""

    print("Querying Claude with updated context...")
    response = anthropic_client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        system=system_instruction,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text

if __name__ == "__main__":
    TARGET_NOTION_PAGE = "your_notion_page_id_here"
    USER_QUERY = "What are the core deliverables mentioned in our project documentation?"
    print("\n--- Claude's Response ---")
    print(query_claude_with_notion_knowledge(TARGET_NOTION_PAGE, USER_QUERY))