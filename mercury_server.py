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
import json, os, sys

HOST="127.0.0.1"
PORT=8765
OLLAMA=os.environ.get("OLLAMA_HOST","http://127.0.0.1:11434").rstrip("/")
WEB_ENDPOINT=os.environ.get("OLLAMA_WEB_SEARCH_URL","https://ollama.com/api/web_search")
ROOT=Path(__file__).resolve().parent

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

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Serve only from this folder.
        if path=="/": path="/Mercury_Writer_v4.html"
        return str(ROOT / path.split("?",1)[0].lstrip("/"))

    def send_json(self, obj, status=200):
        data=jdump(obj)
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/ollama/tags"):
            try:
                self.send_json(get_json(OLLAMA+"/api/tags"))
            except Exception as e:
                self.send_json({"error":str(e)},502)
            return
        return super().do_GET()

    def do_POST(self):
        if self.path!="/api/assistant":
            self.send_error(404); return
        try:
            n=int(self.headers.get("Content-Length","0"))
            body=json.loads(self.rfile.read(n) or b"{}")
            prompt=body.get("prompt","").strip()
            context=body.get("context","")
            model=body.get("model","qwen3:8b")
            history=body.get("history",[])
            use_web=bool(body.get("web"))
            web_text=""
            web_used=False

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

            system = """You are the built-in writing collaborator inside Mercury Writer.
Be concise and useful. You may analyze the supplied manuscript context, but never pretend
to have read material that is not included. Preserve the author's voice when discussing edits.
When web-search material is supplied, distinguish it from manuscript evidence."""
            user_content = prompt
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
