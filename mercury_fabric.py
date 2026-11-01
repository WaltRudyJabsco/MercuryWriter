"""Optional adapter to LOOK's installed client. Mercury owns prompts and memory."""
import importlib
from pathlib import Path
import sys

NODE = 'http://127.0.0.1:7332'


def client():
    core=Path.home()/'.local/share/future-crash-look/core'
    if not (core/'fabric_client.py').is_file():return None
    # Load the bundled client rather than duplicating its trust/transport rules.
    path=str(core)
    if path not in sys.path:sys.path.append(path)
    return importlib.import_module('fabric_client')


def models(get_json):
    try:
        snapshot=get_json(NODE+'/v1/nodes',timeout=.8)
    except (OSError,ValueError):return []
    nodes=[snapshot.get('self') or {}]
    nodes.extend(peer['node'] for peer in snapshot.get('peers',[])
                 if peer.get('trusted') and peer.get('node'))
    result=[]
    for node in nodes:
        name=(node.get('identity') or {}).get('name') or node.get('name') or 'local'
        for model in (node.get('inference') or {}).get('models',[]):
            if model.get('name'):result.append((model['name'],'Fabric · '+name))
    return result


def web_ready(get_json):
    try:
        snapshot=get_json(NODE+'/v1/nodes',timeout=.8)
        return bool((snapshot.get('self') or {}).get('capabilities',{}).get('web.search') or
                    any(peer.get('trusted') and (peer.get('node') or {}).get('capabilities',{}).get('web.search')
                        for peer in snapshot.get('peers',[])))
    except (OSError,ValueError):return False
