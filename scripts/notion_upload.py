"""
将 PaperClaw 学习笔记 Markdown 上传到 Notion。

用法:
  # 列出数据库中所有页面
  python scripts/notion_upload.py --list

  # 归档指定版本的所有页面
  python scripts/notion_upload.py --archive-version v0.01

  # 上传新 markdown 文件（自动归档同版本旧页面）
  python scripts/notion_upload.py --file "docs/diff/PaperClaw_v0.01_Agent初学者学习笔记.md" \
      --version v0.01 --title "PaperClaw v0.01 Agent 初学者学习笔记" \
      --summary "最小 ReAct Coding Agent 的完整设计解析"
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ.get("NOTION_API_TOKEN")
DATABASE_ID = "9da73f3f-e602-49b7-9dc9-c6ea1b76d055"
NOTION_VERSION = "2022-06-28"
MAX_CONTENT = 2000  # Notion rich_text 单段最大字符数
MAX_BATCH = 100  # Notion 单次追加块最大数量

# Notion 代码块支持的 language 标识
NOTION_CODE_LANGS = {
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript",
    "c++", "c#", "css", "dart", "diff", "docker", "elixir", "elm", "erlang",
    "flow", "fortran", "f#", "gherkin", "glsl", "go", "graphql", "groovy",
    "haskell", "html", "java", "javascript", "json", "julia", "kotlin",
    "latex", "less", "lisp", "livescript", "lua", "makefile", "markdown",
    "markup", "matlab", "mermaid", "nix", "objective-c", "ocaml", "pascal",
    "perl", "php", "plain text", "powershell", "prolog", "protobuf", "python",
    "r", "reason", "ruby", "rust", "sass", "scala", "scheme", "scss", "shell",
    "sql", "swift", "typescript", "vb.net", "verilog", "vhdl", "visual basic",
    "webassembly", "yaml",
}

LANG_ALIASES = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "sh": "bash",
    "shell": "bash",
    "ps1": "powershell",
    "yml": "yaml",
    "txt": "plain text",
    "text": "plain text",
}


def normalize_lang(lang: str) -> str:
    """把 markdown fence 语言映射为 Notion 接受的 language 标识。"""
    lang = lang.strip().lower()
    if not lang:
        return "plain text"
    lang = LANG_ALIASES.get(lang, lang)
    return lang if lang in NOTION_CODE_LANGS else "plain text"


def notion_request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"https://api.notion.com/v1/{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        },
        method=method,
    )
    # 429 退避：Notion 限流时短退避重试，避免单批失败导致整体上传中断
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                wait = 2 ** attempt
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                # 重建 request：urlopen 消费了 body stream 后无法重试同一对象
                data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
                req = urllib.request.Request(
                    url, data=data,
                    headers={
                        "Authorization": f"Bearer {TOKEN}",
                        "Content-Type": "application/json",
                        "Notion-Version": NOTION_VERSION,
                    },
                    method=method,
                )
                continue
            err_body = exc.read().decode("utf-8", errors="replace")
            print(f"HTTP {exc.code}: {err_body}", file=sys.stderr)
            raise


# ── Block builders ──────────────────────────────────────────────

def heading_block(level: int, text: str) -> dict:
    block_type = f"heading_{level}"
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": split_rich_text(text)},
    }


def paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": split_rich_text(text)},
    }


def code_block(text: str, lang: str = "plain text") -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": split_rich_text(text),
            "language": normalize_lang(lang),
        },
    }


def quote_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": split_rich_text(text)},
    }


def bullet_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": split_rich_text(text)},
    }


def numbered_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": split_rich_text(text)},
    }


def divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def split_rich_text(text: str) -> list[dict]:
    """Notion rich_text 单段上限 2000 字符，超长时按行切分为多段。"""
    if len(text) <= MAX_CONTENT:
        return [{"type": "text", "text": {"content": text}}]
    parts = []
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > MAX_CONTENT:
            if chunk:
                parts.append({"type": "text", "text": {"content": chunk}})
            chunk = line
            while len(chunk) > MAX_CONTENT:
                parts.append({"type": "text", "text": {"content": chunk[:MAX_CONTENT]}})
                chunk = chunk[MAX_CONTENT:]
        else:
            chunk = chunk + "\n" + line if chunk else line
    if chunk:
        parts.append({"type": "text", "text": {"content": chunk}})
    return parts


def split_code_blocks(text: str, lang: str) -> list[dict]:
    """超长代码块按行切分为多个 code block，避免单块超过 2000 字符。"""
    if len(text) <= MAX_CONTENT:
        return [code_block(text, lang)]
    blocks = []
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > MAX_CONTENT:
            if chunk:
                blocks.append(code_block(chunk, lang))
            chunk = line
            while len(chunk) > MAX_CONTENT:
                blocks.append(code_block(chunk[:MAX_CONTENT], lang))
                chunk = chunk[MAX_CONTENT:]
        else:
            chunk = chunk + "\n" + line if chunk else line
    if chunk:
        blocks.append(code_block(chunk, lang))
    return blocks


def split_paragraph_blocks(text: str) -> list[dict]:
    """超长段落按行切分为多个 paragraph block。"""
    if len(text) <= MAX_CONTENT:
        return [paragraph_block(text)]
    blocks = []
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > MAX_CONTENT:
            if chunk:
                blocks.append(paragraph_block(chunk))
            chunk = line
            while len(chunk) > MAX_CONTENT:
                blocks.append(paragraph_block(chunk[:MAX_CONTENT]))
                chunk = chunk[MAX_CONTENT:]
        else:
            chunk = chunk + "\n" + line if chunk else line
    if chunk:
        blocks.append(paragraph_block(chunk))
    return blocks


# ── Markdown parser ──────────────────────────────────────────────

def markdown_to_blocks(md_text: str) -> list[dict]:
    """逐行解析 Markdown，生成 Notion block 列表。

    支持的元素：
      - 标题 # ~ ######（Notion 只接受 3 级，更深层级降级为 heading_3）
      - 代码块 ```lang ... ```，支持 4/5 反引号嵌套 fence
      - 引用 > text
      - 无序列表 - / *
      - 有序列表 1. 2. 3.
      - 分割线 ---
      - 表格 | ... |（降级为 plain text 代码块）
      - 段落（空行分隔）
    """
    blocks = []
    lines = md_text.split("\n")
    i = 0
    paragraph_lines: list[str] = []

    def flush_paragraph():
        nonlocal paragraph_lines
        if paragraph_lines:
            text = "\n".join(paragraph_lines).strip()
            if text:
                blocks.extend(split_paragraph_blocks(text))
            paragraph_lines = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 代码块（支持 3/4/5 反引号嵌套 fence）
        if stripped.startswith("```"):
            flush_paragraph()
            fence_len = 0
            for ch in stripped:
                if ch == "`":
                    fence_len += 1
                else:
                    break
            fence = "`" * fence_len
            lang = stripped[fence_len:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < len(lines):
                # 结束条件：行只包含相同数量（或更多）的反引号
                inner = lines[i].strip()
                if inner.startswith(fence) and set(inner) == {"`"} and len(inner) >= fence_len:
                    break
                code_lines.append(lines[i])
                i += 1
            code_text = "\n".join(code_lines)
            blocks.extend(split_code_blocks(code_text, lang))
            i += 1
            continue

        # 分割线
        if stripped in ("---", "***", "___") and len(stripped) >= 3:
            flush_paragraph()
            blocks.append(divider_block())
            i += 1
            continue

        # 标题
        if line.startswith("#"):
            flush_paragraph()
            level = 0
            for ch in line:
                if ch == "#":
                    level += 1
                else:
                    break
            text = line[level:].strip()
            # Notion heading 只支持 1-3 级，更深层级降级
            level = min(max(level, 1), 3)
            blocks.append(heading_block(level, text))
            i += 1
            continue

        # 引用
        if line.startswith("> ") or stripped == ">":
            flush_paragraph()
            quote_lines = []
            while i < len(lines) and (lines[i].startswith("> ") or lines[i].strip() == ">"):
                if lines[i].startswith("> "):
                    quote_lines.append(lines[i][2:])
                else:
                    quote_lines.append("")
                i += 1
            text = "\n".join(quote_lines).strip()
            if text:
                blocks.append(quote_block(text))
            continue

        # 无序列表
        if stripped.startswith("- ") or stripped.startswith("* "):
            flush_paragraph()
            while i < len(lines):
                s = lines[i].strip()
                if s.startswith("- ") or s.startswith("* "):
                    blocks.append(bullet_block(s[2:]))
                    i += 1
                else:
                    break
            continue

        # 有序列表
        if re.match(r"^\d+\.\s", line):
            flush_paragraph()
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                text = re.sub(r"^\d+\.\s", "", lines[i].strip())
                blocks.append(numbered_block(text))
                i += 1
            continue

        # 表格（降级为 plain text 代码块）
        if stripped.startswith("|"):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            table_text = "\n".join(table_lines)
            blocks.extend(split_code_blocks(table_text, "plain text"))
            continue

        # 空行
        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # 普通段落
        paragraph_lines.append(line)
        i += 1

    flush_paragraph()
    return blocks


# ── Notion API helpers ──────────────────────────────────────────

def list_pages() -> list[dict]:
    pages = []
    start_cursor = None
    while True:
        query: dict = {"page_size": 100}
        if start_cursor:
            query["start_cursor"] = start_cursor
        result = notion_request("POST", f"databases/{DATABASE_ID}/query", query)
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        start_cursor = result.get("next_cursor")
    return pages


def archive_page(page_id: str) -> None:
    notion_request("PATCH", f"pages/{page_id}", {"archived": True})


def archive_version(version: str) -> int:
    """归档数据库中指定版本的所有未归档页面，返回归档数量。"""
    pages = list_pages()
    archived = 0
    for p in pages:
        props = p.get("properties", {})
        v = ""
        if "版本" in props and props["版本"].get("select"):
            v = props["版本"]["select"].get("name", "")
        if v == version and not p.get("archived"):
            print(f"  Archiving: {p['id']} (v={v})")
            archive_page(p["id"])
            archived += 1
    return archived


def create_page(version: str, title: str, summary: str, doc_type: str = "学习笔记") -> dict:
    body = {
        "parent": {"database_id": DATABASE_ID},
        "icon": {"type": "emoji", "emoji": "📖"},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "版本": {"select": {"name": version}},
            "类型": {"select": {"name": doc_type}},
            "状态": {"select": {"name": "已完成"}},
            "日期": {"date": {"start": time.strftime("%Y-%m-%d")}},
        },
    }
    if summary:
        body["properties"]["摘要"] = {
            "rich_text": [{"text": {"content": summary[:MAX_CONTENT]}}]
        }
    return notion_request("POST", "pages", body)


def append_blocks(page_id: str, blocks: list[dict]) -> None:
    for i in range(0, len(blocks), MAX_BATCH):
        batch = blocks[i:i + MAX_BATCH]
        end = i + len(batch)
        print(f"  Appending blocks {i+1}-{end} of {len(blocks)}...")
        notion_request("PATCH", f"blocks/{page_id}/children", {"children": batch})


# ── CLI ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upload PaperClaw Markdown notes to Notion")
    parser.add_argument("--file", help="Markdown file to upload")
    parser.add_argument("--version", help="Version label (e.g. v0.01)")
    parser.add_argument("--title", help="Page title")
    parser.add_argument("--summary", help="Page summary")
    parser.add_argument("--type", default="学习笔记", help="Document type select")
    parser.add_argument("--list", action="store_true", help="List pages in database")
    parser.add_argument("--archive-version", help="Archive all pages with given version")
    args = parser.parse_args()

    if not TOKEN:
        print("NOTION_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if args.list:
        pages = list_pages()
        print(f"Found {len(pages)} pages:")
        for p in pages:
            props = p.get("properties", {})
            name = ""
            if "Name" in props and props["Name"].get("title"):
                name = props["Name"]["title"][0].get("plain_text", "")
            version = ""
            if "版本" in props and props["版本"].get("select"):
                version = props["版本"]["select"].get("name", "")
            archived = p.get("archived", False)
            print(f"  {p['id']}  v={version}  archived={archived}  title={name}")
        return

    if args.archive_version:
        count = archive_version(args.archive_version)
        print(f"Archived {count} pages (version={args.archive_version})")
        return

    if not args.file or not args.version or not args.title:
        parser.error("--file, --version, --title are required for upload")

    # 1. 归档同版本旧页面
    print(f"Archiving existing {args.version} pages...")
    archived = archive_version(args.version)
    print(f"Archived {archived} old page(s)")

    # 2. 读取 markdown
    print(f"Reading {args.file}...")
    with open(args.file, encoding="utf-8") as f:
        md_text = f.read()

    # 3. 解析为 Notion 块
    print("Parsing markdown...")
    blocks = markdown_to_blocks(md_text)
    print(f"Generated {len(blocks)} blocks")

    # 4. 创建新页面
    print(f"Creating page: {args.title}")
    page = create_page(args.version, args.title, args.summary or "", args.type)
    page_id = page["id"]
    print(f"Page created: {page_id}")

    # 5. 分批追加块
    print("Appending blocks...")
    append_blocks(page_id, blocks)

    url = page.get("url", "N/A")
    print(f"\nDone! Page URL: {url}")


if __name__ == "__main__":
    main()
