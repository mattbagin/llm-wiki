#!/usr/bin/env python3
"""
Local browse + synthesis UI for an LLM Knowledge Wiki.

A thin Flask app that lets you read the wiki and create new pages by synthesis.
Conversions, ingest, and web search stay in the CLI (convert.py / research.py /
search/cli.py) — this UI is intentionally just "read the wiki + write new pages
from what's already in it".

Endpoints:
    GET  /                  Single-page browser (index, search, page view)
    GET  /api/pages         List pages (name, title, page_type)
    GET  /api/page/<name>   Rendered page HTML + metadata
    GET  /api/search?q=     Ranked search results (reuses mcp_server.WikiIndex)
    POST /api/synthesize    {question} → reads relevant pages → LLM-drafts a page
    POST /api/save          {name, page_type, content} → writes wiki/<dir>/<name>.md

Usage:
    pip install flask                  # markdown optional, for nicer rendering
    python tools/wiki_ui.py            # serves http://127.0.0.1:8000
    python tools/wiki_ui.py --port 8080 --repo-root /path/to/wiki

Synthesis and any LLM call require ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import html as _html
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_server  # WikiIndex + parsing helpers (no `mcp` package needed to import)

TODAY = date.today().isoformat()

PAGE_TYPE_DIRS = {
    "entity": "entities",
    "concept": "concepts",
    "topic": "topics",
    "comparison": "comparisons",
    "open-question": "open-questions",
}

_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def render_markdown(md_text: str) -> str:
    """Markdown → HTML, with [[wikilinks]] turned into in-app links."""
    try:
        import markdown as _md

        body = _md.markdown(md_text, extensions=["tables", "fenced_code"])
    except ImportError:
        body = "<pre>" + _html.escape(md_text) + "</pre>"
    # Turn [[name]] (which markdown leaves verbatim) into clickable links.
    return _WIKILINK.sub(lambda m: f'<a href="#" class="wikilink" data-page="{m.group(1)}">{m.group(1)}</a>', body)


def synthesize_page(index, question: str, model: str | None = None) -> dict:
    """Read the most relevant wiki pages and ask the LLM to draft a new page."""
    import research  # reuse the configured Anthropic client + model default

    model = model or research.DEFAULT_MODEL
    hits = index.search(question, max_results=6)
    context_parts = []
    for h in hits:
        page = index.read_page(h["name"])
        if page:
            context_parts.append(f"--- {h['name']} ---\n{page['content'][:2500]}")
    context = "\n\n".join(context_parts) or "No closely related pages found."

    prompt = (
        "You maintain a knowledge wiki. Draft a NEW wiki page that answers/synthesizes "
        "the request below, grounded ONLY in the provided existing pages. Cite pages with "
        "[[wikilinks]]. If the wiki lacks the information, say so in an Open Issues section "
        "rather than inventing facts.\n\n"
        f"Request: {question}\n\n"
        "<existing_pages>\n" + context + "\n</existing_pages>\n\n"
        "Output a complete markdown page: YAML frontmatter (page_type one of "
        "entity|concept|topic|comparison|open-question; title; created: " + TODAY + "; "
        "confidence: low|medium; provenance: public; tags: [..]) then sections "
        "(Summary, Key Points, Cross-References, Source Log, Open Issues)."
    )
    client = research.get_client()
    resp = client.messages.create(model=model, max_tokens=2500, messages=[{"role": "user", "content": prompt}])
    draft = resp.content[0].text
    fm = mcp_server.parse_frontmatter(draft)
    return {
        "draft": draft,
        "suggested_name": _slug(fm.get("title", question)),
        "page_type": fm.get("page_type", "topic"),
    }


def _slug(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:60] or "new-page"


def save_page(wiki_dir: Path, name: str, page_type: str, content: str) -> Path:
    """Write a reviewed page into wiki/<dir>/, append a log entry, and best-effort
    add it to index.md under the matching section."""
    name = _slug(name)
    subdir = PAGE_TYPE_DIRS.get(page_type, "topics")
    target = wiki_dir / subdir
    target.mkdir(parents=True, exist_ok=True)
    page_path = target / f"{name}.md"
    page_path.write_text(content, encoding="utf-8")

    log = wiki_dir / "log.md"
    if log.exists():
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## [{TODAY}] synthesize | {name}\n- Created: wiki/{subdir}/{name}.md (via UI)\n")

    _try_add_to_index(wiki_dir / "index.md", page_type, name)
    return page_path


_SECTION_FOR_TYPE = {
    "entity": "## Entities", "concept": "## Concepts", "topic": "## Topics",
    "comparison": "## Comparisons", "open-question": "## Open Questions",
}


def _try_add_to_index(index_path: Path, page_type: str, name: str) -> None:
    if not index_path.exists():
        return
    section = _SECTION_FOR_TYPE.get(page_type)
    if not section:
        return
    lines = index_path.read_text(encoding="utf-8").splitlines()
    bullet = f"- [[{name}]]"
    if any(f"[[{name}]]" in ln for ln in lines):
        return
    out, inserted = [], False
    for ln in lines:
        out.append(ln)
        if ln.strip() == section and not inserted:
            out.append(bullet)
            inserted = True
    if not inserted:  # section missing — append it
        out += ["", section, bullet]
    index_path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ── Flask app ────────────────────────────────────────────────────────────────


def create_app(repo_root: Path):
    try:
        from flask import Flask, jsonify, request
    except ImportError:
        print("Flask not installed. Run: pip install flask", file=sys.stderr)
        sys.exit(1)

    wiki_dir = repo_root / "wiki"
    index = mcp_server.WikiIndex(wiki_dir)
    app = Flask(__name__)

    @app.get("/")
    def home():
        return INDEX_HTML

    @app.get("/api/pages")
    def api_pages():
        index.refresh()
        return jsonify(index.list_pages())

    @app.get("/api/page/<name>")
    def api_page(name):
        page = index.read_page(name)
        if not page:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "name": page["name"], "title": page["title"], "page_type": page["page_type"],
            "confidence": page["confidence"], "provenance": page["provenance"],
            "html": render_markdown(page["content"]),
        })

    @app.get("/api/search")
    def api_search():
        from flask import request
        q = request.args.get("q", "")
        return jsonify(index.search(q, max_results=20) if q else [])

    @app.post("/api/synthesize")
    def api_synthesize():
        from flask import request
        data = request.get_json(force=True) or {}
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question required"}), 400
        try:
            return jsonify(synthesize_page(index, question))
        except SystemExit:
            return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e)}), 500

    @app.post("/api/save")
    def api_save():
        from flask import request
        data = request.get_json(force=True) or {}
        name, content = data.get("name"), data.get("content")
        if not name or not content:
            return jsonify({"error": "name and content required"}), 400
        path = save_page(wiki_dir, name, data.get("page_type", "topic"), content)
        index.refresh()
        return jsonify({"ok": True, "path": str(path.relative_to(repo_root))})

    return app


INDEX_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>LLM Wiki</title><style>
:root{--fg:#1a1a1a;--mut:#666;--bd:#e2e2e2;--ac:#2563eb;}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--fg)}
#wrap{display:flex;height:100vh}
#side{width:300px;border-right:1px solid var(--bd);padding:14px;overflow:auto;background:#fafafa}
#main{flex:1;padding:28px 40px;overflow:auto;max-width:900px}
input,textarea,select,button{font:inherit}
#q{width:100%;padding:8px;border:1px solid var(--bd);border-radius:6px}
.btn{background:var(--ac);color:#fff;border:0;padding:8px 14px;border-radius:6px;cursor:pointer}
.btn.alt{background:#eee;color:#222}
a.wikilink,.plist a{color:var(--ac);text-decoration:none;cursor:pointer}
.plist{list-style:none;padding:0;margin:8px 0}.plist li{margin:3px 0}
.cat{font-weight:600;margin-top:12px;color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.meta{color:var(--mut);font-size:13px;margin-bottom:16px}
textarea{width:100%;height:340px;padding:10px;border:1px solid var(--bd);border-radius:6px;font-family:ui-monospace,Menlo,monospace;font-size:13px}
pre{background:#f6f6f6;padding:12px;border-radius:6px;overflow:auto}
table{border-collapse:collapse}td,th{border:1px solid var(--bd);padding:4px 8px}
h1,h2,h3{line-height:1.25}.row{display:flex;gap:8px;align-items:center;margin:8px 0}
</style></head><body><div id=wrap>
<div id=side>
  <input id=q placeholder="Search the wiki...">
  <div class=row><button class=btn onclick="showSynth()">+ Synthesize page</button></div>
  <div id=list></div>
</div>
<div id=main><h1>LLM Knowledge Wiki</h1><p class=meta>Select a page, search, or synthesize a new page.</p></div>
</div><script>
const main=document.getElementById('main'),list=document.getElementById('list'),q=document.getElementById('q');
async function loadPages(){const r=await fetch('/api/pages');const ps=await r.json();const by={};
 ps.forEach(p=>{(by[p.page_type]=by[p.page_type]||[]).push(p)});
 list.innerHTML=Object.keys(by).sort().map(t=>`<div class=cat>${t}</div><ul class=plist>`+
  by[t].map(p=>`<li><a onclick="openPage('${p.name}')">${p.title||p.name}</a></li>`).join('')+'</ul>').join('');}
async function openPage(n){const r=await fetch('/api/page/'+encodeURIComponent(n));if(!r.ok){main.innerHTML='<p>Not found.</p>';return;}
 const p=await r.json();main.innerHTML=`<div class=meta>${p.page_type} · confidence ${p.confidence} · provenance ${p.provenance}</div>`+p.html;
 main.querySelectorAll('a.wikilink').forEach(a=>a.onclick=e=>{e.preventDefault();openPage(a.dataset.page)});}
q.addEventListener('input',async()=>{const v=q.value.trim();if(!v){loadPages();return;}
 const r=await fetch('/api/search?q='+encodeURIComponent(v));const rs=await r.json();
 list.innerHTML='<div class=cat>results</div><ul class=plist>'+rs.map(x=>`<li><a onclick="openPage('${x.name}')">${x.title} <span style=color:#999>· ${x.score}</span></a></li>`).join('')+'</ul>';});
function showSynth(){main.innerHTML=`<h2>Synthesize a new page</h2>
 <p class=meta>Drafts a page grounded only in existing wiki content. Review before saving.</p>
 <div class=row><input id=sq style="flex:1;padding:8px;border:1px solid #ddd;border-radius:6px" placeholder="What should this page cover?"></div>
 <div class=row><button class=btn onclick="runSynth()">Draft</button> <span id=sstat class=meta></span></div>
 <textarea id=sdraft placeholder="Draft appears here..."></textarea>
 <div class=row><input id=sname style="flex:1;padding:8px;border:1px solid #ddd;border-radius:6px" placeholder="page-name (slug)">
  <select id=stype><option>topic</option><option>concept</option><option>entity</option><option>comparison</option><option>open-question</option></select>
  <button class="btn alt" onclick="savePage()">Save to wiki/</button></div>`;}
async function runSynth(){const question=document.getElementById('sq').value.trim();if(!question)return;
 const st=document.getElementById('sstat');st.textContent='Synthesizing...';
 const r=await fetch('/api/synthesize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});
 const d=await r.json();if(d.error){st.textContent='Error: '+d.error;return;}
 st.textContent='';document.getElementById('sdraft').value=d.draft;document.getElementById('sname').value=d.suggested_name;
 document.getElementById('stype').value=d.page_type;}
async function savePage(){const name=document.getElementById('sname').value,content=document.getElementById('sdraft').value,page_type=document.getElementById('stype').value;
 const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,content,page_type})});
 const d=await r.json();if(d.error){alert(d.error);return;}alert('Saved: '+d.path);loadPages();openPage(name);}
loadPages();
</script></body></html>"""


def find_repo_root() -> Path:
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "AGENTS.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
        if (parent / "wiki").is_dir() and (parent / "raw").is_dir():
            return parent
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description="Local browse + synthesis UI for an LLM wiki")
    parser.add_argument("--repo-root", type=Path, default=None, help="Wiki repo root (default: auto-detect)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    repo_root = args.repo_root or find_repo_root()
    if not (repo_root / "wiki").is_dir():
        print(f"No wiki/ found under {repo_root}. Run bootstrap.py or pass --repo-root.", file=sys.stderr)
        sys.exit(1)
    app = create_app(repo_root)
    print(f"Serving {repo_root / 'wiki'} at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
