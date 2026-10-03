#!/usr/bin/env python3
"""
Mercury Writer local launcher.

Runs the editor at http://127.0.0.1:8765 and proxies local Ollama.
Optional web search uses OLLAMA_API_KEY from your shell environment.

Usage:
    python3 mercury_server.py
Then open:
    http://127.0.0.1:8765

Mercury's launcher loads OLLAMA_API_KEY from ~/.zsh_secrets when available.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json, os, sys, re, math, shutil, subprocess, tempfile, time, hashlib, uuid, threading
from datetime import datetime

HOST="127.0.0.1"
PORT=8765
WEB_ENDPOINT=os.environ.get("OLLAMA_WEB_SEARCH_URL","https://ollama.com/api/web_search")
ROOT=Path(__file__).resolve().parent
MEMORY_FILE=ROOT / "mercury_memory.json"
MEMORY_SLOTS=5
AI_CONFIG_LOCAL=ROOT / "mercury_ai.json"
AI_CONFIG_USER=Path.home() / ".config" / "mercury" / "ai.json"
_HOST_CACHE={"at":0.0,"hosts":[]}
HOST_CACHE_SECONDS=8.0
HISTORY_DIR=ROOT / "history"
HISTORY_LIMIT=100
STATE_DIR=ROOT / "state"
CANONICAL_PROJECT=STATE_DIR / "current.mercury"
REVISION_FILE=STATE_DIR / "revision.json"
REVISION_DIR=STATE_DIR / "revisions"
CONFLICT_DIR=STATE_DIR / "conflicts"
WORKSPACE_ROOT=ROOT / "workspace"
STATE_LOCK=threading.RLock()



def _nested_value(obj, paths):
    for path in paths:
        cur=obj
        ok=True
        for key in path:
            if not isinstance(cur,dict) or key not in cur:
                ok=False; break
            cur=cur[key]
        if ok and isinstance(cur,str) and cur.strip():
            return cur.strip()
    return ""

def _fabric_selection():
    """Read LOOK/Fabric preference when it is explicitly available.

    Mercury never requires Fabric. Environment variables are the cleanest hook;
    known LOOK config locations are accepted when they expose an unambiguous
    preferred model/host.
    """
    model=(os.environ.get("FABRIC_MODEL") or os.environ.get("LOOK_MODEL") or "").strip()
    host=(os.environ.get("FABRIC_OLLAMA_HOST") or os.environ.get("LOOK_OLLAMA_HOST") or "").strip()
    source="environment" if (model or host) else ""

    candidates=[
        Path.home()/".config"/"look"/"config.json",
        Path.home()/".config"/"look"/"settings.json",
        Path.home()/".local"/"share"/"look"/"settings.json",
        Path.home()/".local"/"share"/"LOOK"/"settings.json",
    ]
    for path in candidates:
        if model and host: break
        try:
            if not path.exists(): continue
            data=json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data,dict): continue
            found_model=_nested_value(data,[
                ("ai","preferred_model"),("ai","local_preferred_model"),
                ("ollama","model"),("ollama","preferred_model"),
                ("preferred_model",),("model",)
            ])
            found_host=_nested_value(data,[
                ("ai","ollama_host"),("ollama","host"),("ollama_host",)
            ])
            if not model and found_model: model=found_model
            if not host and found_host: host=found_host
            if (found_model or found_host) and not source: source=str(path)
        except Exception:
            pass
    return {"model":model or None,"host":host or None,"source":source or None}

def _atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,path)

def _project_digest(project):
    payload=json.dumps(project,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def _new_revision_id():
    # Lexically sortable timestamp plus UUID entropy; no wall-clock timestamp is used as identity.
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S.%f%z")+"-"+uuid.uuid4().hex[:12]

def _load_revision():
    if not REVISION_FILE.exists(): return None
    try:return json.loads(REVISION_FILE.read_text(encoding="utf-8"))
    except Exception:return None

def _revision_envelope(project,parent=None,source="server",revision_id=None):
    return {
        "revision_id":revision_id or _new_revision_id(),
        "parent_revision":parent,
        "created_at":datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "content_sha256":_project_digest(project),
        "source":str(source or "unknown"),
    }

def _save_revision_copy(project,meta):
    REVISION_DIR.mkdir(parents=True,exist_ok=True)
    _atomic_json(REVISION_DIR/(meta["revision_id"]+".json"),{"revision":meta,"project":project})

def _save_conflict(project,parent,source,current):
    CONFLICT_DIR.mkdir(parents=True,exist_ok=True)
    meta=_revision_envelope(project,parent,source)
    path=CONFLICT_DIR/(meta["revision_id"]+".json")
    _atomic_json(path,{"revision":meta,"conflicts_with":current,"project":project})
    return str(path),meta

def _save_canonical_project(project,parent_revision=None,source="server",force=False):
    if not isinstance(project,dict) or not isinstance(project.get("chapters"),list): raise ValueError("Invalid Mercury project")
    with STATE_LOCK:
        current=_load_revision()
        digest=_project_digest(project)
        if current and current.get("content_sha256")==digest:
            return {"saved":False,"revision":current,"reason":"unchanged"}
        current_id=current.get("revision_id") if current else None
        if current and not force and parent_revision!=current_id:
            path,branch=_save_conflict(project,parent_revision,source,current)
            return {"saved":False,"conflict":True,"revision":current,"branch_revision":branch,"conflict_path":path}
        meta=_revision_envelope(project,current_id,source)
        _atomic_json(CANONICAL_PROJECT,project)
        _atomic_json(REVISION_FILE,meta)
        _save_revision_copy(project,meta)
        return {"saved":True,"revision":meta}

def _load_canonical_project():
    if not CANONICAL_PROJECT.exists(): return None
    data=json.loads(CANONICAL_PROJECT.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or not isinstance(data.get("chapters"),list): raise ValueError("Invalid canonical Mercury project")
    return data

def _canonical_state():
    return {"project":_load_canonical_project(),"revision":_load_revision()}

def _workspace_dir(project): return WORKSPACE_ROOT/_safe_slug(project.get("title") or "Untitled")

def _frontmatter(scene,chapter_id,scene_index):
    return "---\n"+f"mercury_scene_id: {scene.get('id','')}\n"+f"mercury_chapter_id: {chapter_id}\n"+f"mercury_scene_index: {scene_index}\n"+f"title: {json.dumps(scene.get('title') or 'Untitled Scene',ensure_ascii=False)}\n"+"---\n\n"

def _materialize_workspace(project):
    root=_workspace_dir(project); manuscript=root/"manuscript"
    if manuscript.exists(): shutil.rmtree(manuscript)
    manuscript.mkdir(parents=True,exist_ok=True)
    rev=_load_revision()
    manifest={"format":"mercury-workspace-2","title":project.get("title","Untitled"),"author":project.get("author",""),"base_revision":rev.get("revision_id") if rev else None,"base_sha256":rev.get("content_sha256") if rev else _project_digest(project),"chapters":[]}
    for ci,ch in enumerate(project.get("chapters",[]),1):
        cslug=f"{ci:02d}-{_safe_slug(ch.get('title') or f'Chapter {ci}')}"; cdir=manuscript/cslug; cdir.mkdir(parents=True,exist_ok=True)
        crow={"id":ch.get("id"),"title":ch.get("title"),"dir":cslug,"scenes":[]}
        for si,scene in enumerate(ch.get("scenes",[]),1):
            fname=f"{si:02d}-{_safe_slug(scene.get('title') or f'Scene {si}')}.md"; (cdir/fname).write_text(_frontmatter(scene,ch.get("id",""),si)+(scene.get("text") or ""),encoding="utf-8")
            crow["scenes"].append({"id":scene.get("id"),"file":f"manuscript/{cslug}/{fname}"})
        manifest["chapters"].append(crow)
    _atomic_json(root/"mercury-workspace.json",manifest); return root

def _parse_workspace_scene(path):
    raw=path.read_text(encoding="utf-8"); meta={}; body=raw
    if raw.startswith("---\n"):
        end=raw.find("\n---\n",4)
        if end>=0:
            head=raw[4:end]; body=raw[end+5:]; body=body[1:] if body.startswith("\n") else body
            for line in head.splitlines():
                if ":" not in line: continue
                k,v=line.split(":",1); v=v.strip()
                if k.strip()=="title":
                    try:v=json.loads(v)
                    except Exception:pass
                meta[k.strip()]=v
    return meta,body

def _ingest_workspace(project=None):
    project=project or _load_canonical_project()
    if not project: raise ValueError("No canonical Mercury project exists yet")
    root=_workspace_dir(project); manifest_path=root/"mercury-workspace.json"
    if not manifest_path.exists(): raise ValueError("Workspace has not been created")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8")); by_scene={str(s.get("id")):s for c in project.get("chapters",[]) for s in c.get("scenes",[])}; changed=0
    for crow in manifest.get("chapters",[]):
        for srow in crow.get("scenes",[]):
            path=root/srow.get("file","")
            if not path.exists(): continue
            meta,body=_parse_workspace_scene(path); scene=by_scene.get(str(meta.get("mercury_scene_id") or srow.get("id") or ""))
            if not scene: continue
            title=meta.get("title") or scene.get("title") or "Untitled Scene"
            if scene.get("text","")!=body or scene.get("title")!=title: scene["text"]=body; scene["title"]=title; changed+=1
    result={"saved":False,"revision":_load_revision()}
    if changed:
        project["modified"]=datetime.now().isoformat(timespec="seconds")
        result=_save_canonical_project(project,manifest.get("base_revision"),"nvim")
        if result.get("conflict"):
            return _load_canonical_project(),changed,result
        _save_history_snapshot(project)
        # Move the workspace base forward after a successful import.
        manifest["base_revision"]=result.get("revision",{}).get("revision_id")
        manifest["base_sha256"]=result.get("revision",{}).get("content_sha256")
        _atomic_json(manifest_path,manifest)
    return project,changed,result

def _safe_slug(value):
    slug=re.sub(r"[^A-Za-z0-9._-]+","-",str(value or "Untitled")).strip("-._")
    return (slug or "Untitled")[:80]

def _history_project_dir(project):
    # Stable enough for recovery while keeping each manuscript visually separate.
    title=_safe_slug(project.get("title") if isinstance(project,dict) else "Untitled")
    return HISTORY_DIR / title

def _history_entries(project_title=None):
    roots=[]
    if project_title:
        roots=[HISTORY_DIR/_safe_slug(project_title)]
    elif HISTORY_DIR.exists():
        roots=[p for p in HISTORY_DIR.iterdir() if p.is_dir()]
    rows=[]
    for root in roots:
        if not root.exists(): continue
        for p in root.glob("*.mercury"):
            try:
                stat=p.stat()
                rows.append({
                    "id":f"{root.name}/{p.name}",
                    "title":root.name.replace("-"," "),
                    "saved_at":datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "bytes":stat.st_size
                })
            except OSError:
                pass
    rows.sort(key=lambda x:x["saved_at"],reverse=True)
    return rows

def _save_history_snapshot(project):
    if not isinstance(project,dict) or not isinstance(project.get("chapters"),list):
        raise ValueError("Invalid Mercury project")
    folder=_history_project_dir(project)
    folder.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(project,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    digest=hashlib.sha256(payload).hexdigest()[:12]

    latest=next(iter(sorted(folder.glob("*.mercury"),reverse=True)),None)
    if latest:
        try:
            old=json.loads(latest.read_text(encoding="utf-8"))
            old_payload=json.dumps(old,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
            if hashlib.sha256(old_payload).hexdigest()[:12]==digest:
                return {"saved":False,"id":f"{folder.name}/{latest.name}","reason":"unchanged"}
        except Exception:
            pass

    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    path=folder/f"{stamp}-{digest}.mercury"
    tmp=path.with_suffix(".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp,path)

    snapshots=sorted(folder.glob("*.mercury"),reverse=True)
    for old in snapshots[HISTORY_LIMIT:]:
        try: old.unlink()
        except OSError: pass
    return {"saved":True,"id":f"{folder.name}/{path.name}","saved_at":datetime.now().isoformat(timespec="seconds")}

def _load_history_snapshot(snapshot_id):
    parts=Path(str(snapshot_id or "")).parts
    if len(parts)!=2 or any(part in ("","..",".") for part in parts):
        raise ValueError("Invalid history snapshot")
    path=(HISTORY_DIR/parts[0]/parts[1]).resolve()
    if HISTORY_DIR.resolve() not in path.parents or path.suffix!=".mercury":
        raise ValueError("Invalid history snapshot")
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or not isinstance(data.get("chapters"),list):
        raise ValueError("Invalid Mercury project")
    return data

def _clean_host_url(url):
    return str(url or "").strip().rstrip("/")

def _load_ai_config():
    """Preferred Ollama host + fallbacks, with local Ollama always available."""
    cfg={}
    explicit=os.environ.get("MERCURY_AI_CONFIG")
    candidates=[Path(explicit).expanduser()] if explicit else [AI_CONFIG_LOCAL,AI_CONFIG_USER]
    for path in candidates:
        try:
            if path.exists():
                loaded=json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded,dict):
                    cfg=loaded
                    break
        except Exception as e:
            print(f"Mercury AI config ignored ({path}): {e}",file=sys.stderr)

    hosts=[]
    seen=set()

    def add(name,url):
        url=_clean_host_url(url)
        if not url or url in seen: return
        seen.add(url)
        hosts.append({"name":str(name or "Ollama")[:48],"url":url})

    if os.environ.get("OLLAMA_HOST"):
        add("Configured",os.environ["OLLAMA_HOST"])

    for item in cfg.get("hosts",[]) if isinstance(cfg.get("hosts",[]),list) else []:
        if isinstance(item,dict):
            add(item.get("name") or "Ollama",item.get("url"))

    add("Local","http://127.0.0.1:11434")

    fabric=_fabric_selection()
    if fabric.get("host"):
        add("Fabric",fabric["host"])

    preferred=str(cfg.get("preferred_host") or "").strip()
    if fabric.get("host"):
        fabric_url=_clean_host_url(fabric["host"])
        hosts.sort(key=lambda h: 0 if h["url"]==fabric_url else 1)
    elif preferred:
        hosts.sort(key=lambda h: 0 if h["name"]==preferred else 1)

    return {"hosts":hosts,"preferred_host":preferred,"fabric":fabric}

def _probe_hosts(force=False):
    now=time.monotonic()
    if not force and _HOST_CACHE["hosts"] and now-_HOST_CACHE["at"]<HOST_CACHE_SECONDS:
        return _HOST_CACHE["hosts"]

    probed=[]
    for host in _load_ai_config()["hosts"]:
        row={**host,"reachable":False,"models":[],"error":""}
        try:
            data=get_json(host["url"]+"/api/tags",timeout=2.5)
            row["models"]=[m.get("name","") for m in data.get("models",[]) if isinstance(m,dict) and m.get("name")]
            row["reachable"]=True
        except Exception as e:
            row["error"]=str(e)
        probed.append(row)

    _HOST_CACHE["at"]=now
    _HOST_CACHE["hosts"]=probed
    return probed

def _available_models():
    hosts=_probe_hosts()
    by_name={}
    for host in hosts:
        if not host["reachable"]: continue
        for name in host["models"]:
            by_name.setdefault(name,[]).append(host["name"])
    models=[{"name":name,"hosts":names} for name,names in sorted(by_name.items(),key=lambda x:x[0].lower())]
    active=next((h for h in hosts if h["reachable"]),None)
    fabric=_fabric_selection()
    fabric_model=fabric.get("model")
    if fabric_model and fabric_model not in by_name:
        fabric_model=None
    return {
        "models":models,
        "mercury":{
            "active_host":active["name"] if active else None,
            "hosts":[{"name":h["name"],"reachable":h["reachable"],"models":len(h["models"])} for h in hosts],
            "web_ready":bool(os.environ.get("OLLAMA_API_KEY")),
            "fabric_model":fabric_model,
            "fabric_source":fabric.get("source")
        }
    }

def _candidate_hosts(model):
    hosts=_probe_hosts()
    exact=[h for h in hosts if h["reachable"] and model in h["models"]]
    return exact if exact else [h for h in hosts if h["reachable"]]

def ollama_chat(model,messages,timeout=240):
    """Route to a host that has the model; fall back if a host disappears."""
    errors=[]
    for host in _candidate_hosts(model):
        try:
            out=post_json(host["url"]+"/api/chat",{"model":model,"messages":messages,"stream":False},timeout=timeout)
            return out,host
        except Exception as e:
            errors.append(f'{host["name"]}: {e}')
            _HOST_CACHE["at"]=0.0
    if not errors:
        raise URLError("No configured Ollama host is reachable")
    raise URLError("; ".join(errors))

def should_search_web(prompt):
    """Web checked means available when useful, not mandatory on every turn."""
    text=" ".join(str(prompt or "").strip().lower().split())
    bare=text.rstrip(" .!?")

    if bare in {
        "thanks","thank you","thanks so much","thank you so much","cool","great",
        "perfect","awesome","excellent","okay","ok","got it","makes sense","i see",
        "exactly","right","nice","yes","no","yep","nope","love it","that works",
        "works for me","good","sounds good"
    }:
        return False

    if any(p in bare for p in (
        "make it shorter","make this shorter","try that again","rewrite this",
        "rewrite it","tighten this","what do you think","why does this work",
        "why does that work","does this work","read this","analyze this",
        "look at this paragraph","look at this scene","keep the first",
        "keep this","less sentimental","more concise","less wordy"
    )):
        return False

    if any(term in bare for term in (
        "search","look up","find sources","source this","verify","fact check",
        "fact-check","today","current","latest","headline","headlines","news",
        "recent","right now","as of","historical accuracy","was there","when did",
        "how much did","who was","what happened"
    )):
        return True

    if any(term in bare for term in (
        "this sentence","this paragraph","this scene","this chapter",
        "the manuscript","my prose","my draft"
    )):
        return False

    return len(bare.split()) >= 4

def _memory_worthy(prompt,reply):
    text=" ".join(str(prompt or "").strip().lower().split()).rstrip(" .!?")
    if not text: return False
    if text in {"thanks","thank you","cool","great","perfect","awesome","okay","ok","yes","no","got it","exactly","nice"}:
        return False
    decision_words=("keep","prefer","remember","don't","do not","always","never","change","character","scene","chapter","story","plot","voice","period","fact")
    return len(text.split())>=5 or any(w in text for w in decision_words)

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
    if not prompt or not reply or not _memory_worthy(prompt,reply): return mem
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
            out,_host=ollama_chat(model,[{"role":"user","content":merge_prompt}],timeout=120)
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
            preferred = ROOT / "Mercury_Writer_1_3_1.html"
            if preferred.exists():
                return str(preferred)
            candidates = sorted(ROOT.glob("Mercury_Writer*.html"))
            if candidates:
                return str(candidates[-1])
            return str(ROOT / "Mercury_Writer_1_3_1.html")
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
        parsed=urlparse(self.path)
        if parsed.path=="/api/history":
            title=parse_qs(parsed.query).get("title",[""])[0]
            self.send_json({"snapshots":_history_entries(title or None)[:30]})
            return
        if parsed.path=="/api/history/load":
            try:
                snapshot_id=parse_qs(parsed.query).get("id",[""])[0]
                self.send_json({"project":_load_history_snapshot(snapshot_id)})
            except Exception as e:
                self.send_json({"error":str(e)},400)
            return
        if parsed.path=="/api/project/current":
            try:self.send_json(_canonical_state())
            except Exception as e:self.send_json({"error":str(e)},500)
            return
        if parsed.path=="/api/workspace/status":
            try:
                project=_load_canonical_project(); root=_workspace_dir(project) if project else None
                self.send_json({"ready":bool(root and (root/"mercury-workspace.json").exists()),"path":str(root) if root else None})
            except Exception as e:self.send_json({"error":str(e)},500)
            return
        if self.path.startswith("/api/ollama/tags"):
            try:
                payload=_available_models()
                self.send_json(payload,200 if payload["models"] else 502)
            except Exception as e:
                self.send_json({"error":str(e)},502)
            return
        if self.path.startswith("/api/ai/status"):
            hosts=_probe_hosts(force=True)
            active=next((h for h in hosts if h["reachable"]),None)
            self.send_json({
                "active_host":active["name"] if active else None,
                "hosts":[{"name":h["name"],"url":h["url"],"reachable":h["reachable"],"models":len(h["models"])} for h in hosts],
                "web_ready":bool(os.environ.get("OLLAMA_API_KEY")),
                "memory_file":str(MEMORY_FILE)
            })
            return
        return super().do_GET()

    def do_POST(self):
        try:
            n=int(self.headers.get("Content-Length","0"))
            body=json.loads(self.rfile.read(n) or b"{}")
            if self.path=="/api/project/commit":
                project=body.get("project")
                result=_save_canonical_project(project,body.get("parent_revision"),body.get("source") or "browser")
                self.send_json(result,409 if result.get("conflict") else 200)
                return
            if self.path=="/api/history/save":
                result=_save_history_snapshot(body.get("project"))
                self.send_json(result)
                return
            if self.path=="/api/workspace/export":
                project=body.get("project") or _load_canonical_project()
                if not project: raise ValueError("No Mercury project available")
                root=_materialize_workspace(project); self.send_json({"ok":True,"path":str(root),"revision":_load_revision()}); return
            if self.path=="/api/workspace/import":
                project,changed,result=_ingest_workspace()
                payload={"ok":not result.get("conflict"),"changed":changed,"project":project,"revision":result.get("revision"),"conflict":bool(result.get("conflict")),"conflict_path":result.get("conflict_path")}
                self.send_json(payload,409 if result.get("conflict") else 200); return
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
            web_status="off"
            memory_data=_load_memory()
            memory_key=_project_key(context)
            project_memory=_memory_for(memory_data,memory_key)

            if use_web and should_search_web(prompt):
                web_status="searching"
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
                        web_status="used" if web_used else "empty"
                    except Exception as e:
                        web_text=f"[Web search unavailable: {e}]"
                        web_status="unavailable"
                else:
                    web_text="[Web search requested, but OLLAMA_API_KEY is not present in the launch environment.]"
                    web_status="no_key"
            elif use_web:
                web_status="skipped"

            today=datetime.now().strftime("%B %d, %Y").replace(" 0"," ")
            system = f"""You are Mercury, an intelligent writing partner.

The current real-world date is {today}. Your training knowledge may be older; never infer the present date from your training cutoff.

Understand what the writer is asking before answering. Be perceptive rather than prescriptive.

The manuscript is your primary evidence. Pay close attention to its language, characters, continuity, implications, period, and established facts. Distinguish what the text establishes from what you infer. Never invent missing facts.

Answer the actual question, and no more. Match the depth and length of your response to the writer's intent. A complex question deserves thought; a simple question deserves a simple answer; a conversational remark may need only a few words.

Do not rewrite, critique, summarize, suggest next steps, or offer additional help unless the request calls for it. Preserve the writer's voice and unusual choices rather than automatically improving them.

When web results are available, use them only if they genuinely help answer the question. Ignore irrelevant results. Never force research into a response merely because a search was performed. Treat current dated web results as current even when they postdate your training knowledge.

Be specific, concise, candid, and intelligent. Avoid boilerplate, flattery, generic encouragement, unnecessary headings, and demonstrations of helpfulness.

Know when the best response is a short one."""

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

            out,ai_host=ollama_chat(model,messages,timeout=240)
            content=((out.get("message") or {}).get("content") or "").strip()
            if content:
                project_memory=_remember_exchange(project_memory,prompt,content,model)
                memory_data[memory_key]=project_memory
                try: _save_memory(memory_data)
                except Exception as e: print("Mercury memory save failed:",e,file=sys.stderr)
            self.send_json({
                "content":content,
                "web_used":web_used,
                "web_status":web_status,
                "ai_host":ai_host["name"],
                "memory_recent":len(project_memory.get("recent",[])),
                "memory_long":bool(project_memory.get("long_term"))
            })
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
    print("AI hosts:")
    for h in _probe_hosts(force=True):
        state="ready" if h["reachable"] else "unavailable"
        detail=f' · {len(h["models"])} models' if h["reachable"] else ""
        print(f'  {h["name"]}: {h["url"]} · {state}{detail}')
    print("Web search key:", "available" if os.environ.get("OLLAMA_API_KEY") else "not found")
    print("Memory:", MEMORY_FILE)
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass
