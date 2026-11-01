"""Revision exchange for Mercury. Transport and pairing belong to Fabric.

Never pick a winner by time: only ancestry permits an automatic fast-forward.
"""
import json
import re

SYNC_BYTES = 6 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9_.+\-]{1,160}\Z")


def enabled(server):
    try:
        return json.loads(server.CONFIG_FILE.read_text()).get("sync_enabled") is True
    except (OSError, ValueError):
        return False


def excluded(server):
    try:return set(json.loads((server.LIBRARY_DIR/'sync-excluded.json').read_text()))
    except (OSError,ValueError):return set()


def exclude(server,pid,value):
    values=excluded(server)
    if value:values.add(pid)
    else:values.discard(pid)
    server._atomic_json(server.LIBRARY_DIR/'sync-excluded.json',sorted(values))


def configure(server, value):
    if not isinstance(value, bool):
        raise ValueError("enabled must be a boolean")
    with server.store_transaction():
        try:
            config = json.loads(server.CONFIG_FILE.read_text())
        except (OSError, ValueError):
            config = {}
        config["sync_enabled"] = value
        server._atomic_json(server.CONFIG_FILE, config)
    return status(server)


def resolve(server, pid, rid, expected):
    """An explicit choice creates a new revision acknowledging both branches."""
    if not isinstance(rid,str) or not ID.fullmatch(rid):
        raise ValueError('Invalid conflict revision')
    with server.store_transaction():
        current=server._lrev(pid)
        if not current or current['revision_id']!=expected:
            raise ValueError('Project changed; inspect conflicts again before resolving')
        path=server._lf(pid,'conflicts')/(rid+'.json')
        row=json.loads(path.read_text())
        return server._lcommit(row['project'],expected,'conflict-resolution',merge_parents=[rid])


def records(server):
    result = {}
    policies = {item['project_id']: item.get('availability') for item in server._llib()['projects']}
    for directory in (server.LIBRARY_DIR / 'projects').glob('*'):
        pid = directory.name
        # Fabric-only entries remain metadata-only on this endpoint.
        if pid in excluded(server) or policies.get(pid) == "fabric-only":
            continue
        for path in server._lf(pid, "revisions").glob("*.json"):
            value = json.loads(path.read_text())
            result[pid + ":" + value["revision"]["revision_id"]] = value
    return result


def status(server):
    with server.store_transaction():
        revisions = records(server)
        heads = {item["project_id"]: item["revision_id"]
                 for item in server._llib()["projects"]
                 if item.get("availability") != "fabric-only" and item.get("revision_id")}
        conflicts = []
        offline = []
        for item in server._llib()["projects"]:
            pid = item["project_id"]
            current = server._lrev(pid) or {}
            ready=False
            for directory in server._documents_replica_dirs(pid):
                try:
                    project=json.loads((directory/'project.mercury').read_text())
                    receipt=json.loads((directory/'mercury-replica.json').read_text())
                    ready=ready or (receipt.get('project_id')==pid and
                        receipt.get('revision',{}).get('revision_id')==current.get('revision_id') and
                        server._project_digest(project)==current.get('content_sha256'))
                except (OSError,ValueError):pass
            offline.append({'project_id':pid,'title':item.get('title'),'ready':ready,
                            'revision_id':current.get('revision_id')})
            for path in server._lf(pid, "conflicts").glob("*.json"):
                row = json.loads(path.read_text())
                rid = row["revision"]["revision_id"]
                if not ancestor(revisions, pid, rid, current.get("revision_id")):
                    conflicts.append({"project_id": pid, "title": item.get("title"),
                                      "revision_id": rid, "path": str(path)})
        return {"enabled": enabled(server), "have": list(revisions), "heads": heads,
                "conflicts": conflicts, "transport": "paired Fabric nodes",
                "documents_dir": server._mcfg()["documents_dir"],"offline":offline}


def ancestor(rows, pid, old, new):
    pending = [new]
    seen = set()
    while pending:
        rid = pending.pop()
        if rid == old and rid is not None:
            return True
        if not rid or rid in seen:
            continue
        seen.add(rid)
        meta = rows.get(pid + ":" + rid, {}).get("revision", {})
        pending.extend([meta.get("parent_revision"), *meta.get("merge_parents", [])])
    return False


def export(server, have=()):
    if not enabled(server):
        raise ValueError("Enable Fabric sync in Mercury Project settings on this node first")
    with server.store_transaction():
        rows = records(server)
        known = set(have)
        outgoing = []
        size = 0
        for key, row in rows.items():
            if key in known:
                continue
            length = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
            if length > SYNC_BYTES:
                raise ValueError("A revision exceeds the 6 MiB Fabric exchange limit; export it manually")
            if size + length > SYNC_BYTES:
                break
            outgoing.append(row)
            size += length
        state = status(server)
        return {"revisions": outgoing, "have": state["have"], "heads": state["heads"]}


def exchange(server, body):
    if not enabled(server):
        raise ValueError("Mercury Fabric sync is disabled on this node")
    if not isinstance(body, dict) or not isinstance(body.get("revisions", []), list):
        raise ValueError("Invalid Mercury exchange")
    if not isinstance(body.get('heads',{}),dict) or not isinstance(body.get('have',[]),list) or not all(isinstance(key,str) for key in body.get('have',[])):
        raise ValueError('Invalid revision inventory')
    for pid,rid in body.get('heads',{}).items():
        server._lf(pid,'revisions')
        if not isinstance(rid,str) or not ID.fullmatch(rid):raise ValueError('Invalid head revision')
    if len(json.dumps(body).encode()) > 8 * 1024 * 1024:
        raise ValueError("Exchange too large")
    with server.store_transaction():
        existing = records(server)
        incoming = {}
        blocked=excluded(server)|{item['project_id'] for item in server._llib()['projects'] if item.get('availability')=='fabric-only'}
        for row in body.get("revisions", []):
            project, revision = row.get("project"), row.get("revision")
            if not isinstance(project, dict) or not isinstance(project.get("chapters"), list) or not isinstance(revision, dict):
                raise ValueError("Invalid Mercury revision")
            server._validate_project(project)
            pid, rid = project.get("project_id"), revision.get("revision_id")
            server._lf(pid, "revisions")  # Validate stable project ID before touching disk.
            if not isinstance(rid, str) or not ID.fullmatch(rid):
                raise ValueError("Invalid revision ID")
            if not isinstance(revision.get('created_at'),str) or not revision['created_at'] or len(revision['created_at'])>80:
                raise ValueError('Invalid revision timestamp')
            if not isinstance(revision.get('merge_parents',[]),list):raise ValueError('Invalid merge parents')
            parents = [revision.get("parent_revision"), *revision.get("merge_parents", [])]
            if any(parent is not None and (not isinstance(parent, str) or not ID.fullmatch(parent)) for parent in parents):
                raise ValueError("Invalid revision ancestry")
            if revision.get("content_sha256") != server._project_digest(project):
                raise ValueError("Revision digest does not match manuscript")
            if pid in blocked:continue
            key = pid + ":" + rid
            if key in existing and existing[key] != row:
                raise ValueError("Revision identity collision; existing revision preserved")
            if key in incoming and incoming[key] != row:
                raise ValueError("Duplicate revision identity")
            incoming[key] = row
        graph={**existing,**incoming};completed=set()
        for key in incoming:
            pending=[(key,False)];visiting=set()
            while pending:
                current,leaving=pending.pop()
                if leaving:
                    visiting.discard(current);completed.add(current);continue
                if current in visiting:raise ValueError('Cyclic revision ancestry')
                if current in completed or current not in graph:continue
                visiting.add(current);pending.append((current,True))
                pid=current.split(':',1)[0];meta=graph[current]['revision']
                for parent in [meta.get('parent_revision'),*meta.get('merge_parents',[])]:
                    if parent:pending.append((pid+':'+parent,False))
        # Validate the entire batch before writing any part of it.
        for key, row in incoming.items():
            pid = row["project"]["project_id"]
            if key not in existing:
                server._atomic_json(server._lf(pid, "revisions") / (row["revision"]["revision_id"] + ".json"), row)
        rows = {**existing, **incoming}
        applied, conflicts, pending = [], [], []
        for pid, rid in body.get("heads", {}).items():
            server._lf(pid, "revisions")
            if pid in blocked:continue
            if any(item['project_id'] == pid and item.get('availability') == 'fabric-only'
                   for item in server._llib()['projects']):
                continue
            row = rows.get(pid + ":" + str(rid))
            if not row:
                pending.append(pid)
                continue
            current = server._lrev(pid)
            if current and current["revision_id"] == rid:
                continue
            if current and ancestor(rows, pid, rid, current["revision_id"]):
                continue  # Never roll back to an older peer.
            if current and not ancestor(rows, pid, current["revision_id"], rid):
                server._atomic_json(server._lf(pid, "conflicts") / (rid + ".json"),
                                    {**row, "conflicts_with": current})
                conflicts.append(pid)
                continue
            # A new replica waits for a complete ancestry chain, including chunks.
            check = [rid]; seen = set(); complete = True
            while check:
                parent = check.pop()
                if not parent or parent in seen:
                    continue
                seen.add(parent)
                record = rows.get(pid + ":" + parent)
                if not record:
                    complete = False; break
                meta = record["revision"]
                check.extend([meta.get("parent_revision"), *meta.get("merge_parents", [])])
            if not complete:
                pending.append(pid); continue
            project, revision = row["project"], row["revision"]
            server._atomic_json(server._lf(pid, "project.mercury"), project)
            server._atomic_json(server._lf(pid, "revision.json"), revision)
            lib = server._llib()
            item = next((item for item in lib["projects"] if item["project_id"] == pid), None)
            if item is None:
                item = {"project_id": pid, "availability": "always-local"}
                lib["projects"].append(item)
            item.update(title=project.get("title", "Untitled"), author=project.get("author", ""),
                        revision_id=rid, content_sha256=revision["content_sha256"], updated_at=revision["created_at"])
            server._atomic_json(server.LIBRARY_INDEX, lib)
            server._mirror_docs(project, revision)
            applied.append(pid)
        result = export(server, body.get("have", []))
        result.update(applied=applied, conflicts=conflicts, pending=pending)
        return result
