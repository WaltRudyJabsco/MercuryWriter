"""A recoverable workspace per terminal session; never delete another editor's files."""
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid


def scene_path(root, scene):
    def slug(value):
        return re.sub(r'[^\w-]+', '-', str(value), flags=re.UNICODE).strip('-')[:80] or 'untitled'
    chapter = f"{scene['chapter_index']+1:02d}-{slug(scene['chapter_title'])}"
    name = f"{scene['scene_index']+1:02d}-{slug(scene['scene_title'])}.md"
    return root/'manuscript'/chapter/name


def atomic_text(path, text):
    fd, name = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


class Session:
    def __init__(self, base, bundle, request, root=None):
        pid = str(bundle['project_id'])
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',pid):raise ValueError('Invalid project ID')
        parent=Path.home()/'.cache/mercury/workspaces'/pid
        if not root:parent.mkdir(parents=True,exist_ok=True)
        self.root=Path(root) if root else Path(tempfile.mkdtemp(prefix='session-',dir=parent))
        self.base=base; self.request=request; self.bundle=json.loads(json.dumps(bundle))
        self.revision=(bundle.get('revision') or {}).get('revision_id')
        self.scenes=[dict(scene) for scene in bundle['scenes']]
        self.baseline={scene['scene_id']:scene['text'] for scene in self.scenes}
        self.additions=self.bundle.get('pending_additions',[])
        self.renames=self.bundle.get('pending_renames',{})
        self.lock=threading.RLock();self.conflict=False;self.changed=0;self.error=''
        for index,scene in enumerate(self.scenes):
            path=scene_path(self.root,scene)
            # Older recovery sessions use numbered files; never strand those drafts.
            legacy=self.root/f'{index+1:04d}.md'
            if root and legacy.is_file():path=legacy
            if root and scene.get('path'):
                saved=Path(scene['path'])
                if saved.resolve().is_relative_to(self.root.resolve()) and saved.is_file():path=saved
            scene['path']=str(path)
            if not root:
                path.parent.mkdir(parents=True,exist_ok=True)
                atomic_text(path,scene['text'])
            else:scene['text']=Path(scene['path']).read_text(encoding='utf-8')
        self.record()

    def record(self):
        atomic_text(self.root/'session.json',json.dumps({'server':self.base,'bundle':self.bundle,
            'base_revision':self.revision,'conflict':self.conflict,'error':self.error},ensure_ascii=False,indent=2))

    def checkpoint(self, scenes):
        with self.lock:
            for scene in scenes:
                path=Path(scene['path'])
                if path.read_text(encoding='utf-8')!=scene['text']:atomic_text(path,scene['text'])

    def add(self,kind,anchor,title=''):
        with self.lock:
            if self.conflict:raise RuntimeError('Resolve the saved conflict before adding manuscript sections')
            if kind not in ('scene','chapter'):raise ValueError('Choose scene or chapter')
            title=title.strip()
            if len(title)>200:raise ValueError('Use a title of 200 characters or fewer')
            selected=next(scene for scene in self.scenes if scene['scene_id']==anchor)
            if kind=='chapter':
                chapter_index=max([scene['chapter_index'] for scene in self.scenes]+[len(self.bundle.get('chapters',[]))-1])+1
                chapter_id=uuid.uuid4().hex;chapter_title=title or f'Chapter {chapter_index+1}'
                scene_index=0;scene_title='Scene 1';index=len(self.scenes)
            else:
                chapter_id=selected['chapter_id'];chapter_title=selected['chapter_title'];chapter_index=selected['chapter_index']
                siblings=[(i,s) for i,s in enumerate(self.scenes) if s['chapter_id']==chapter_id]
                scene_index=max(s['scene_index'] for _,s in siblings)+1
                scene_title=title or f'Scene {scene_index+1}';index=siblings[-1][0]+1
            scene=dict(chapter_id=chapter_id,chapter_title=chapter_title,chapter_index=chapter_index,
                       scene_id=uuid.uuid4().hex,scene_title=scene_title,scene_index=scene_index,text='')
            path=scene_path(self.root,scene);path.parent.mkdir(parents=True,exist_ok=True)
            # Duplicate titles must never overwrite another scene's recovery file.
            if path.exists():path=path.with_name(path.stem+'-'+scene['scene_id']+'.md')
            scene['path']=str(path);atomic_text(path,'')
            self.scenes.insert(index,scene);self.baseline[scene['scene_id']]=''
            self.bundle['scenes'].insert(index,dict(scene))
            self.additions.append(dict(kind=kind,**{key:scene[key] for key in ('chapter_id','chapter_title','scene_id','scene_title')}))
            self.bundle['pending_additions']=self.additions
            self.record()
            return scene

    def rename(self,kind,anchor,title):
        title=title.strip()
        if not title or len(title)>200:
            raise ValueError('Enter a title of 1–200 characters')
        with self.lock:
            if self.conflict:
                raise RuntimeError('Resolve the saved conflict before renaming')
            selected=next(scene for scene in self.scenes if scene['scene_id']==anchor)
            field=kind+'_id'
            identity=selected[field]
            self.renames.setdefault(kind,{})[identity]=title
            self.bundle['pending_renames']=self.renames
            for scene, saved in zip(self.scenes,self.bundle['scenes']):
                if scene[field]==identity:
                    scene[kind+'_title']=saved[kind+'_title']=title
                    saved['path']=scene['path']
            self.record()

    def save(self):
        with self.lock:
            if self.conflict:raise RuntimeError(f'Conflict preserved. Recovery files: {self.root}')
            patches=[]
            for scene in self.scenes:
                text=Path(scene['path']).read_text(encoding='utf-8')
                if text!=self.baseline[scene['scene_id']]:patches.append({'scene_id':scene['scene_id'],'text':text})
            additions=[dict(item,text=Path(next(s['path'] for s in self.scenes if s['scene_id']==item['scene_id'])).read_text(encoding='utf-8')) for item in self.additions]
            if not patches and not additions and not self.renames:
                self.error='';self.record();return 'Saved · no pending edits'
            try:
                code,result=self.request(self.base,'/api/library/apply',{'project_id':self.bundle['project_id'],
                    'base_revision':self.revision,'scenes':patches,'additions':additions,'renames':self.renames,'source':'terminal-desk'},20)
                if code==409 or result.get('conflict'):
                    self.conflict=True;raise RuntimeError('Concurrent draft preserved; resolve it in mercury conflicts')
                if code>=400:raise RuntimeError(result.get('error','Save failed'))
                if additions and result.get('added')!=len(additions):raise RuntimeError('This Mercury server needs the chapter/scene update; new sections remain in local recovery')
                if self.renames and result.get('renamed')!=sum(map(len,self.renames.values())):
                    raise RuntimeError('This Mercury server needs the rename update; titles remain in local recovery')
                self.renames.clear()
                self.bundle.pop('pending_renames',None)
                self.revision=(result.get('revision') or {}).get('revision_id') or self.revision
                for patch in patches:
                    self.baseline[patch['scene_id']]=patch['text']
                    for scene in self.bundle['scenes']:
                        if scene['scene_id']==patch['scene_id']:scene['text']=patch['text']
                self.additions.clear();self.bundle.pop('pending_additions',None)
                self.changed+=result.get('changed',0);self.error='';self.record()
                return 'Saved to Mercury · '+str(result.get('changed',0))+' scene(s)'
            except Exception as error:
                self.error=str(error);self.record();raise

    def edit(self, editor='mini', split=False, scene=None):
        stop=threading.Event()
        def watch():
            while not stop.wait(2):
                try:self.save()
                except Exception:pass  # Files + receipt remain available for explicit recovery.
        watcher=threading.Thread(target=watch,name='mercury-save',daemon=True);watcher.start()
        try:
            initial=next((i+1 for i,item in enumerate(self.scenes) if scene and scene.casefold() in item['scene_title'].casefold()),1)
            if editor=='mini':
                import mercury_desk
                mercury_desk.run(self.scenes,self.checkpoint,self.save,split=split,initial=initial-1,add=self.add,rename=self.rename)
            else:
                manifest=self.root/'desk.json'
                atomic_text(manifest,json.dumps({'scenes':self.scenes,'split':split,'initial':initial}))
                if editor in ('nvim','nvim-desk'):
                    binary=shutil.which('nvim')
                    if not binary:raise RuntimeError('Neovim is unavailable; use --editor mini or install Neovim')
                    if editor=='nvim-desk':
                        env=dict(os.environ,MERCURY_SESSION=str(manifest),MERCURY_DESK_LUA=str(Path(__file__).with_suffix('.lua').with_name('mercury_desk.lua')))
                        command=[binary,'-u','NONE','-i','NONE','-n','-c','lua dofile(vim.env.MERCURY_DESK_LUA)']
                    else:
                        # Let Neovim load the user's usual config and directory browser.
                        manuscript=self.root/'manuscript'
                        target=self.scenes[initial-1]['path'] if scene or not manuscript.is_dir() else str(manuscript)
                        command=[binary]
                        if split:
                            command+=['-o',self.scenes[initial-1]['path'],self.scenes[initial % len(self.scenes)]['path']]
                        else:command.append(target)
                        env=None
                else:
                    command=shlex.split(os.environ.get('EDITOR') or 'vi')+[self.scenes[initial-1]['path']];env=None
                result=subprocess.run(command,env=env)
                if result.returncode:raise RuntimeError(f'Editor exited {result.returncode}; recovery files: {self.root}')
        finally:
            stop.set();watcher.join(timeout=22)
        self.save()
        return {'changed':self.changed,'workspace':str(self.root),'revision_id':self.revision}
