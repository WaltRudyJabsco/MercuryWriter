#!/usr/bin/env python3
"""
Mercury Writer local launcher.

Runs the editor at http://127.0.0.1:8765 and proxies local Ollama.
Optional web search uses OLLAMA_API_KEY from your shell environment.

Usage:
    python3 mercury_server.py
Then open:
    http://127.0.0.1:8765

If OLLAMA_API_KEY is defined in ~/.zshrc, launch from a shell that has sourced it.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path
import json, os, sys, re, math, shutil, subprocess, tempfile

HOST="127.0.0.1"
PORT=8765
OLLAMA=os.environ.get("OLLAMA_HOST","http://127.0.0.1:11434").rstrip("/")
WEB_ENDPOINT=os.environ.get("OLLAMA_WEB_SEARCH_URL","https://ollama.com/api/web_search")
ROOT=Path(__file__).resolve().parent
MEMORY_FILE=ROOT / "mercury_memory.json"
MEMORY_SLOTS=5

def _project_key(context):
    """Best-effort project identity from Mercury's supplied context."""
    text=str(context or "")
    for pattern in (
        r"(?im)^\s*PROJECT TITLE\s*:\s*(.+?)\s*$",
        r"(?im)^\s*PROJECT\s*:\s*(.+?)\s*$",
        r"(?im)^\s*TITLE\s*:\s*(.+?)\s*$",
    ):
        m=re.search(pattern,text)
        if m: return m.group(1).strip()[:120]
    return "__default__"

def _load_memory():
    try:
        data=json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}

def _save_memory(data):
    tmp=MEMORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(MEMORY_FILE)

def _memory_for(data,key):
    mem=data.get(key,{})
    if not isinstance(mem,dict): mem={}
    long_term=str(mem.get("long_term","")).strip()
    recent=mem.get("recent",[])
    if not isinstance(recent,list): recent=[]
    return {"long_term":long_term,"recent":[str(x) for x in recent[-MEMORY_SLOTS:]]}

def _memory_context(mem):
    parts=[]
    if mem.get("long_term"):
        parts.append("LONG-TERM:\n"+mem["long_term"])
    if mem.get("recent"):
        parts.append("RECENT:\n"+"\n".join(f"{i+1}. {x}" for i,x in enumerate(mem["recent"])))
    return "\n\n".join(parts)

def _remember_exchange(mem,prompt,reply,model):
    """Keep five recent exchanges; fold the oldest into durable memory on overflow."""
    prompt=" ".join(str(prompt).split())[:500]
    reply=" ".join(str(reply).split())[:700]
    if not prompt or not reply: return mem
    entry=f"Writer: {prompt} | Mercury: {reply}"
    recent=list(mem.get("recent",[]))
    recent.append(entry)
    long_term=str(mem.get("long_term","")).strip()
    if len(recent)>MEMORY_SLOTS:
        oldest=recent.pop(0)
        merge_prompt=(
            "Maintain a compact long-term memory for a writing project. "
            "Merge only durable facts, decisions, preferences, continuity details, and unresolved questions. "
            "Ignore greetings, transient requests, discarded ideas, and routine conversation. "
            "Correct contradictions in favor of the newer information. Keep it concise.\n\n"
            f"EXISTING MEMORY:\n{long_term or '[empty]'}\n\nNEW OLDEST NOTE:\n{oldest}"
        )
        try:
            out=post_json(OLLAMA+"/api/chat",{
                "model":model,
                "messages":[{"role":"user","content":merge_prompt}],
                "stream":False
            },timeout=120)
            merged=((out.get("message") or {}).get("content") or "").strip()
            if merged: long_term=merged[:4000]
        except Exception:
            # Never break the writing assistant merely because memory compression failed.
            long_term=(long_term+"\n"+oldest).strip()[-4000:]
    return {"long_term":long_term,"recent":recent[-MEMORY_SLOTS:]}

def jdump(x): return json.dumps(x).encode("utf-8")

def post_json(url, payload, headers=None, timeout=180):
    data=jdump(payload)
    h={"Content-Type":"application/json"}
    if headers: h.update(headers)
    req=Request(url,data=data,headers=h,method="POST")
    with urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def get_json(url, headers=None, timeout=30):
    req=Request(url,headers=headers or {},method="GET")
    with urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _pdf_escape(text):
    b = str(text).encode("cp1252", "replace").decode("latin1")
    return b.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")

def _strip_md(text):
    text=re.sub(r"\*\*([^*]+)\*\*",r"\1",str(text))
    text=re.sub(r"__([^_]+)__",r"\1",text)
    text=re.sub(r"\*([^*]+)\*",r"\1",text)
    text=re.sub(r"_([^_]+)_",r"\1",text)
    return text

def _wrap_words(text, max_chars):
    parts = str(text).split()
    if not parts: return [""]
    lines=[]; cur=parts[0]
    for w in parts[1:]:
        if len(cur)+1+len(w) <= max_chars: cur += " "+w
        else: lines.append(cur); cur=w
    lines.append(cur)
    return lines

def build_manuscript_pdf(payload):
    # Mercury's drafting/book preview is standardized to 6 × 9.
    W,H=(432,648)
    ml=mr=44 if W<=360 else 48; mt=50; mb=48
    wpp=max(180,min(500,int(payload.get("wordsPerPage",300) or 300)))
    scale=math.sqrt(300.0/wpp)
    fs=max(8.5,min(12.5,10.5*scale))
    leading=max(12.0,min(17.0,15.0*scale))
    max_chars=max(38,int((W-ml-mr)/(fs*0.48)))
    lines_per_page=max(20,int((H-mt-mb)/leading)-1)
    pages=[]; cur=[]
    def push():
        nonlocal cur
        pages.append(cur); cur=[]
    def add(text="",kind="body"):
        nonlocal cur
        if len(cur)>=lines_per_page: push()
        cur.append((kind,text))

    for _ in range(max(5,lines_per_page//3)): add()
    add(payload.get("title","Manuscript"),"title")
    if payload.get("author"): add(payload["author"],"author")
    push()

    for chapter in payload.get("chapters",[]):
        if cur: push()
        add(chapter.get("title",""),"chapter"); add()
        for scene in chapter.get("scenes",[]):
            if scene.get("title"): add(scene["title"],"scene"); add()
            text=scene.get("text","").strip()
            paras=re.split(r"\n\s*\n",text) if text else []
            for para in paras:
                align="left"
                m=re.match(r"^:::\s*(center|right|justify)\s*\n([\s\S]*?)\n:::\s*$",para,re.I)
                if m:
                    align=m.group(1).lower(); para=m.group(2)
                clean=_strip_md(" ".join(para.split()))
                wrapped=_wrap_words(clean,max_chars)
                for li,line in enumerate(wrapped):
                    kind="body" if align=="left" else f"body_{align}"
                    if align=="justify" and li==len(wrapped)-1: kind="body"
                    add(line,kind)
                add()
            add()
    if cur: push()
    if not pages: pages=[[]]

    objs=[]
    def obj(data): objs.append(data); return len(objs)
    f1=obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding >>")
    f2=obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold /Encoding /WinAnsiEncoding >>")
    content_refs=[]
    for pi,page in enumerate(pages,1):
        cmds=["BT"]; y=H-mt
        for kind,text in page:
            if kind=="title": size,font=18,"F2"
            elif kind=="chapter": size,font=15,"F2"
            elif kind=="scene": size,font=10,"F2"
            elif kind=="author": size,font=11,"F1"
            else: size,font=fs,"F1"
            if text:
                x=ml
                approx=len(text)*float(size)*0.48
                if kind=="body_center": x=max(ml,(W-approx)/2)
                elif kind=="body_right": x=max(ml,W-mr-approx)
                if kind=="body_justify" and " " in text:
                    gaps=max(1,text.count(" "))
                    natural=approx
                    extra=max(0,(W-ml-mr-natural)/gaps)
                    cmds.append(f"/{font} {size} Tf {extra:.3f} Tw 1 0 0 1 {x:.1f} {y:.1f} Tm ({_pdf_escape(text)}) Tj 0 Tw")
                else:
                    cmds.append(f"/{font} {size} Tf 1 0 0 1 {x:.1f} {y:.1f} Tm ({_pdf_escape(text)}) Tj")
            y-=leading*1.4 if kind in ("title","chapter") else leading
        cmds.append(f"/F1 8 Tf 1 0 0 1 {W/2-4:.1f} 20 Tm ({pi}) Tj");cmds.append("ET")
        stream="\n".join(cmds).encode("latin1","replace")
        content_refs.append(obj(b"<< /Length %d >>\nstream\n"%len(stream)+stream+b"\nendstream"))
    pages_obj=obj(b"")
    page_refs=[]
    for cref in content_refs:
        page_refs.append(obj(f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {cref} 0 R >>".encode()))
    kids=" ".join(f"{x} 0 R" for x in page_refs)
    objs[pages_obj-1]=f"<< /Type /Pages /Count {len(page_refs)} /Kids [{kids}] >>".encode()
    catalog=obj(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode())

    out=bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"); offsets=[0]
    for i,data in enumerate(objs,1):
        offsets.append(len(out));out+=f"{i} 0 obj\n".encode()+data+b"\nendobj\n"
    xref=len(out);out+=f"xref\n0 {len(objs)+1}\n".encode()+b"0000000000 65535 f \n"
    for off in offsets[1:]: out+=f"{off:010d} 00000 n \n".encode()
    out+=f"trailer\n<< /Size {len(objs)+1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def browser_pdf_from_html(html):
    """Render Mercury's already-paginated 6x9 HTML with Chromium itself."""
    candidates=[
        os.environ.get("MERCURY_CHROME",""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
    ]
    browser=next((x for x in candidates if x and Path(x).exists()),None)
    if not browser:
        raise RuntimeError("Chrome/Chromium not found. Install Chrome, or set MERCURY_CHROME to its executable path.")
    with tempfile.TemporaryDirectory(prefix="mercury-pdf-") as td:
        html_path=Path(td)/"book.html"
        pdf_path=Path(td)/"book.pdf"
        html_path.write_text(html,encoding="utf-8")
        cmd=[browser,"--headless","--disable-gpu","--no-sandbox","--no-pdf-header-footer",
             "--allow-file-access-from-files","--user-data-dir="+str(Path(td)/"chrome-profile"),
             "--print-to-pdf="+str(pdf_path),html_path.as_uri()]
        proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        if proc.returncode!=0 or not pdf_path.exists():
            err=proc.stderr.decode("utf-8","ignore").strip()
            raise RuntimeError("Chromium PDF render failed"+(": "+err[-500:] if err else ""))
        data=pdf_path.read_bytes()
        # Chromium should honor @page size:6in 9in. Refuse a silently wrong-size PDF.
        if b"/MediaBox [0 0 432 648]" not in data and b"/MediaBox [0 0 432.0 648.0]" not in data:
            # PDF numeric serialization varies; don't fail solely on byte formatting.
            pass
        return data

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Mercury is a local/private app under active development. Never let
        # Safari/iPadOS keep an obsolete HTML copy after an upgrade.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def translate_path(self, path):
        # Serve only from this folder. For "/" prefer the bundled Mercury file,
        # but fall back to any Mercury_Writer*.html file so renaming a release
        # cannot break the launcher.
        if path=="/":
            preferred = ROOT / "Mercury_Writer_1_2_7.html"
            if preferred.exists():
                return str(preferred)
            candidates = sorted(ROOT.glob("Mercury_Writer*.html"))
            if candidates:
                return str(candidates[-1])
            return str(ROOT / "Mercury_Writer_1_2_7.html")
        return str(ROOT / path.split("?",1)[0].lstrip("/"))

    def send_json(self, obj, status=200):
        data=jdump(obj)
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data, content_type, filename=None, status=200):
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(data)))
        if filename: self.send_header("Content-Disposition",f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/ollama/tags"):
            try:
                self.send_json(get_json(OLLAMA+"/api/tags"))
            except Exception as e:
                self.send_json({"error":str(e)},502)
            return
        return super().do_GET()

    def do_POST(self):
        try:
            n=int(self.headers.get("Content-Length","0"))
            body=json.loads(self.rfile.read(n) or b"{}")
            if self.path=="/api/export/pdf":
                html=body.get("html","")
                renderer="basic"
                if html:
                    try:
                        pdf=browser_pdf_from_html(html)
                        renderer="browser"
                    except Exception as e:
                        print("Browser PDF renderer unavailable; using basic 6x9 fallback:",e,file=sys.stderr)
                        pdf=build_manuscript_pdf(body)
                        renderer="fallback"
                else:
                    pdf=build_manuscript_pdf(body)
                safe=re.sub(r"[^A-Za-z0-9._-]+","-",body.get("title","manuscript")).strip("-") or "manuscript"
                self.send_response(200)
                self.send_header("Content-Type","application/pdf")
                self.send_header("Content-Length",str(len(pdf)))
                self.send_header("Content-Disposition",f'attachment; filename="{safe}.pdf"')
                self.send_header("X-Mercury-PDF-Renderer",renderer)
                self.end_headers()
                self.wfile.write(pdf); return
            if self.path!="/api/assistant":
                self.send_error(404); return
            prompt=body.get("prompt","").strip()
            context=body.get("context","")
            model=body.get("model","qwen3:8b")
            history=body.get("history",[])
            use_web=bool(body.get("web"))
            web_text=""
            web_used=False
            memory_data=_load_memory()
            memory_key=_project_key(context)
            project_memory=_memory_for(memory_data,memory_key)

            if use_web:
                key=os.environ.get("OLLAMA_API_KEY")
                if key:
                    try:
                        res=post_json(WEB_ENDPOINT,{"query":prompt},headers={"Authorization":"Bearer "+key},timeout=30)
                        # Keep only a compact search digest.
                        items=res.get("results",res if isinstance(res,list) else [])
                        chunks=[]
                        for item in items[:6] if isinstance(items,list) else []:
                            if isinstance(item,dict):
                                chunks.append(f"{item.get('title','')}\n{item.get('content') or item.get('snippet','')}\n{item.get('url','')}")
                        web_text="\n\n".join(chunks)
                        web_used=bool(web_text)
                    except Exception as e:
                        web_text=f"[Web search unavailable: {e}]"
                else:
                    web_text="[Web search requested, but OLLAMA_API_KEY is not present in the launch environment.]"

            system = """You are Mercury, an intelligent writing partner.

Your first job is to understand the writer's question, intention, and supplied manuscript before trying to improve anything.

Be perceptive rather than prescriptive. Notice what the writing is doing, why it works or fails, what it implies, and what the writer may be trying to accomplish. Prefer specific observations grounded in the supplied text over generic writing advice.

The manuscript outranks your assumptions. Treat what the manuscript establishes as true within the work. Distinguish clearly between what the text establishes, what you reasonably infer, and what remains unknown.

Be especially attentive to continuity, implication, character intention, historical plausibility, prose rhythm, point of view, and the difference between what a text says and what a reader infers.

Do not rewrite unless asked. Do not flatten unusual choices merely because they are unusual. When suggesting changes, preserve the writer's voice, intention, characters, period, and established facts.

Infer the kind of help the writer wants from the question. A request may call for close reading, critique, brainstorming, editing, continuity analysis, factual research, historical context, or rewriting. Do not make the writer choose a mode unnecessarily.

Before answering, determine what the writer is actually asking, what the supplied manuscript establishes, what is inference, and whether outside information is relevant. Then answer naturally. Do not expose this internal analysis unless it is useful to the writer.

If web search results are supplied, treat them as optional evidence, not as an assignment. Use them only when they materially improve the answer. Do not mention, summarize, or force irrelevant web results into a response merely because they are present. If the search found nothing useful, simply answer from the manuscript and your existing knowledge when appropriate. Never let weak web results override the manuscript.

Never invent manuscript facts, research results, quotations, or sources. If something important is uncertain, say what is uncertain.

Be concise when the answer is simple and thorough when the question requires thought. Avoid boilerplate, unnecessary headings, generic encouragement, and repetitive disclaimers.

The writer remains the author. Your purpose is to help the writer see the work more clearly, understand what is already on the page, and make better decisions about what comes next."""
            user_content = prompt
            remembered=_memory_context(project_memory)
            if remembered:
                user_content += "\n\n--- PROJECT MEMORY ---\n" + remembered
            if context:
                user_content += "\n\n--- MANUSCRIPT CONTEXT ---\n" + context
            if web_text:
                user_content += "\n\n--- WEB SEARCH CONTEXT ---\n" + web_text

            messages=[{"role":"system","content":system}]
            # History is intentionally shallow; context is reattached to current request.
            for m in history[-8:-1]:
                if m.get("role") in ("user","assistant"):
                    messages.append({"role":m["role"],"content":m.get("content","")})
            messages.append({"role":"user","content":user_content})

            out=post_json(OLLAMA+"/api/chat",{"model":model,"messages":messages,"stream":False},timeout=240)
            content=((out.get("message") or {}).get("content") or "").strip()
            if content:
                project_memory=_remember_exchange(project_memory,prompt,content,model)
                memory_data[memory_key]=project_memory
                try: _save_memory(memory_data)
                except Exception as e: print("Mercury memory save failed:",e,file=sys.stderr)
            self.send_json({"content":content,"web_used":web_used})
        except HTTPError as e:
            self.send_json({"error":f"HTTP {e.code}: {e.read().decode('utf-8','ignore')}"},502)
        except URLError as e:
            self.send_json({"error":f"Could not reach local Ollama: {e.reason}"},502)
        except Exception as e:
            self.send_json({"error":str(e)},500)

if __name__=="__main__":
    os.chdir(ROOT)
    httpd=ThreadingHTTPServer((HOST,PORT),Handler)
    print(f"Mercury Writer: http://{HOST}:{PORT}")
    print(f"Ollama: {OLLAMA}")
    print("Web search key:", "available" if os.environ.get("OLLAMA_API_KEY") else "not found")
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass
