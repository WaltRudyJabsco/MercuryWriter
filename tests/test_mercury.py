import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
import os
import shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import mercury_sync
from mercury_desk import Buffer,wrapped,move_vertical
from mercury_session import Session
from install_core import install


def server_at(root):
    name='test_mercury_'+uuid.uuid4().hex
    spec=importlib.util.spec_from_file_location(name,ROOT/'mercury_server.py')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    paths={'ROOT':root,'LIBRARY_DIR':root/'library','LIBRARY_INDEX':root/'library/library.json',
           'CONFIG_FILE':root/'config.json','DEFAULT_DOCUMENTS_DIR':root/'documents',
           'CANONICAL_PROJECT':root/'state/current.mercury','REVISION_FILE':root/'state/revision.json',
           'REVISION_DIR':root/'state/revisions','CONFLICT_DIR':root/'state/conflicts',
           'STATE_DIR':root/'state','HISTORY_DIR':root/'history','WORKSPACE_ROOT':root/'workspace',
           'MEMORY_FILE':root/'memory.json','EPOCH_FILE':root/'epoch.json','RESET_BACKUP_DIR':root/'backups'}
    for key,value in paths.items():setattr(module,key,value)
    module._lboot();return module


def manuscript():
    return {'project_id':'book-1','title':'A Book','chapters':[{'id':'c1','title':'One','scenes':[
        {'id':'s1','title':'Arrival','text':'First draft','notes':''},
        {'id':'s2','title':'Departure','text':'Another scene','notes':''}]}]}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.a=server_at(self.root/'a');self.b=server_at(self.root/'b')
        self.p=manuscript()

    def tearDown(self):self.temp.cleanup()

    def commit(self,server,project=None,parent=None):
        return server._save_canonical_project(copy.deepcopy(project or self.p),parent)

    def exchange(self,source,target):
        mercury_sync.configure(source,True);mercury_sync.configure(target,True)
        return mercury_sync.exchange(target,mercury_sync.export(source))

    def test_browser_and_cli_share_head(self):
        first=self.commit(self.a)
        result=self.a._lapply('book-1',first['revision']['revision_id'],[{'scene_id':'s2','text':'CLI edit'}],'test')
        self.assertEqual(self.a._canonical_state()['revision'],result['revision'])
        self.assertEqual(self.a._load_canonical_project()['chapters'][0]['scenes'][1]['text'],'CLI edit')
        stale=self.commit(self.a,parent=first['revision']['revision_id'])
        self.assertTrue(stale['conflict']);self.assertTrue(Path(stale['conflict_path']).exists())

    def test_concurrent_saves_cannot_both_advance(self):
        first=self.commit(self.a);barrier=threading.Barrier(2);results=[]
        other_server=server_at(self.root/'a')
        def save(server,text):
            p=copy.deepcopy(self.p);p['chapters'][0]['scenes'][0]['text']=text;barrier.wait()
            results.append(self.commit(server,p,first['revision']['revision_id']))
        threads=[threading.Thread(target=save,args=(server,text)) for server,text in [(self.a,'one'),(other_server,'two')]]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(sum(bool(row.get('conflict')) for row in results),1)

    def test_revision_snapshot_is_authoritative_after_projection_failure(self):
        result=self.commit(self.a)
        self.a._atomic_json(self.a._lf('book-1','project.mercury'),{'damaged':'projection'})
        self.assertEqual(self.a._lproj('book-1'),self.p)

    def test_offline_replica_and_safe_fast_forward(self):
        first=self.commit(self.a);self.exchange(self.a,self.b)
        self.assertEqual(self.b._lrev('book-1'),first['revision'])
        self.assertTrue(list(self.b.DEFAULT_DOCUMENTS_DIR.glob('*/project.mercury')))
        p=copy.deepcopy(self.p);p['chapters'][0]['scenes'][0]['text']='offline change'
        changed=self.commit(self.b,p,first['revision']['revision_id'])
        result=self.exchange(self.b,self.a)
        self.assertEqual(result['applied'],['book-1'])
        self.assertEqual(self.a._lrev('book-1'),changed['revision'])

    def test_offline_readiness_checks_latest_revision_and_detects_damage(self):
        self.commit(self.a)
        self.assertTrue(mercury_sync.status(self.a)['offline'][0]['ready'])
        replica=self.a._documents_replica_dirs('book-1')[0]/'project.mercury'
        replica.write_text('{}')
        self.assertFalse(mercury_sync.status(self.a)['offline'][0]['ready'])

    def test_documents_failure_reports_warning_without_losing_saved_revision(self):
        from unittest.mock import patch
        with patch.object(self.a,'_mirror_docs',side_effect=OSError('disk unavailable')):
            result=self.commit(self.a)
        self.assertTrue(result['saved']);self.assertIn('disk unavailable',result['replica_error'])
        self.assertEqual(self.a._lproj('book-1'),self.p)
        self.assertFalse(mercury_sync.status(self.a)['offline'][0]['ready'])

    def test_ai_uses_installed_fabric_client_and_lists_its_models(self):
        from unittest.mock import Mock,patch
        adapter=Mock();adapter.infer.return_value={'message':{'content':'reply'},'fabric_node':'paired-node'}
        with patch.object(self.a.mercury_fabric,'client',return_value=adapter),patch.object(self.a.mercury_fabric,'models',return_value=[('writing-model','Fabric · paired-node')]),patch.object(self.a,'_probe_hosts',return_value=[]),patch.object(self.a.mercury_fabric,'web_ready',return_value=False):
            models=self.a._available_models()['models']
            self.assertEqual(models,[{'name':'writing-model','hosts':['Fabric · paired-node']}])
            reply,host=self.a.ollama_chat('writing-model',[{'role':'user','content':'writing context'}])
        self.assertEqual(reply['message']['content'],'reply');self.assertIn('paired-node',host['name'])
        self.assertEqual(adapter.infer.call_args.kwargs['owner'],'mercury-writer')

    def test_divergent_edits_are_preserved_and_resolution_replicates(self):
        first=self.commit(self.a);self.exchange(self.a,self.b)
        left=copy.deepcopy(self.p);right=copy.deepcopy(self.p)
        left['chapters'][0]['scenes'][0]['text']='left';right['chapters'][0]['scenes'][0]['text']='right'
        local=self.commit(self.a,left,first['revision']['revision_id'])
        remote=self.commit(self.b,right,first['revision']['revision_id'])
        result=self.exchange(self.b,self.a)
        self.assertEqual(result['conflicts'],['book-1'])
        self.assertEqual(self.a._lproj('book-1'),left)
        resolved=mercury_sync.resolve(self.a,'book-1',remote['revision']['revision_id'],local['revision']['revision_id'])
        self.exchange(self.a,self.b)
        self.assertEqual(self.b._lrev('book-1'),resolved['revision'])
        self.assertEqual(self.b._lproj('book-1'),right)
        self.assertEqual(mercury_sync.status(self.a)['conflicts'],[])

    def test_old_peer_never_rolls_back(self):
        first=self.commit(self.a);self.exchange(self.a,self.b)
        p=copy.deepcopy(self.p);p['title']='New title';new=self.commit(self.a,p,first['revision']['revision_id'])
        self.exchange(self.b,self.a);self.assertEqual(self.a._lrev('book-1'),new['revision'])

    def test_chunks_wait_for_ancestry(self):
        first=self.commit(self.a);p=copy.deepcopy(self.p);p['title']='New';second=self.commit(self.a,p,first['revision']['revision_id'])
        mercury_sync.configure(self.a,True);mercury_sync.configure(self.b,True)
        payload=mercury_sync.export(self.a)
        rows=payload['revisions'];head=next(row for row in rows if row['revision']==second['revision'])
        result=mercury_sync.exchange(self.b,{**payload,'revisions':[head]})
        self.assertEqual(result['pending'],['book-1']);self.assertIsNone(self.b._lproj('book-1'))
        result=mercury_sync.exchange(self.b,{**payload,'revisions':[row for row in rows if row!=head]})
        self.assertEqual(result['applied'],['book-1'])

    def test_invalid_batch_writes_nothing(self):
        self.commit(self.a);mercury_sync.configure(self.a,True);mercury_sync.configure(self.b,True)
        payload=mercury_sync.export(self.a);bad=copy.deepcopy(payload['revisions'][0]);bad['revision']['content_sha256']='bad'
        payload['revisions'].append(bad)
        with self.assertRaises(ValueError):mercury_sync.exchange(self.b,payload)
        self.assertFalse(list((self.b.LIBRARY_DIR/'projects').glob('*/revisions/*.json')))

    def test_deleted_local_project_stays_deleted_after_sync(self):
        self.commit(self.a);self.exchange(self.a,self.b)
        self.a._delete_library_project('book-1')
        self.exchange(self.b,self.a)
        self.assertIsNone(self.a._lproj('book-1'))
        self.assertEqual(self.a._llib()['projects'],[])
        deleted=self.a._trash_entries()[0]
        self.a._restore_library_project(deleted['trash_id'])
        self.assertEqual(self.a._lproj('book-1'),self.p)

    def test_path_traversal_rejected(self):
        p=copy.deepcopy(self.p);p['project_id']='../../escape'
        with self.assertRaises(ValueError):self.commit(self.a,p)

    def test_cyclic_or_malformed_sync_batch_is_rejected(self):
        self.commit(self.a);mercury_sync.configure(self.a,True);mercury_sync.configure(self.b,True)
        payload=mercury_sync.export(self.a)
        revision=payload['revisions'][0]['revision'];revision['parent_revision']=revision['revision_id']
        with self.assertRaisesRegex(ValueError,'Cyclic'):mercury_sync.exchange(self.b,payload)
        self.assertIsNone(self.b._lproj('book-1'))

    def test_rename_reuses_offline_replica_and_unmarked_folder_is_not_overwritten(self):
        occupied=self.a.DEFAULT_DOCUMENTS_DIR/'A Book';occupied.mkdir(parents=True)
        (occupied/'project.mercury').write_text('unrelated')
        first=self.commit(self.a);replicas=self.a._documents_replica_dirs('book-1')
        p=copy.deepcopy(self.p);p['title']='Renamed'
        self.commit(self.a,p,first['revision']['revision_id'])
        self.assertEqual(self.a._documents_replica_dirs('book-1'),replicas)
        self.assertEqual((occupied/'project.mercury').read_text(),'unrelated')

    def test_project_deep_link_serves_editor_and_private_paths_are_not_static(self):
        self.a.ROOT=ROOT;handler=self.a.Handler.__new__(self.a.Handler)
        self.assertEqual(Path(handler.translate_path('/?project=book-1')).name,'Mercury_Writer_1_6_0.html')
        for path in ['/mercury_server.py','/library/library.json','/../README.md','/%2e%2e/README.md']:
            self.assertEqual(Path(handler.translate_path(path)).name,'.missing-public-resource')

    def test_reset_disables_sync_and_archives(self):
        self.commit(self.a);mercury_sync.configure(self.a,True)
        result=self.a._factory_reset()
        self.assertFalse(mercury_sync.enabled(self.a));self.assertFalse(self.a._llib()['projects'])
        self.assertTrue(list(self.a.RESET_BACKUP_DIR.glob('*.zip')))

    def test_session_conflict_retains_local_text(self):
        first=self.commit(self.a)
        def request(base,path,body,timeout):
            result=self.a._lapply(body['project_id'],body['base_revision'],body['scenes'],body['source'])
            return (409 if result.get('conflict') else 200),result
        # Redirect session workspaces to the disposable test home.
        from unittest.mock import patch
        with patch('mercury_session.Path.home',return_value=self.root):
            one=Session('local',self.a._lbundle('book-1'),request)
            two=Session('local',self.a._lbundle('book-1'),request)
        self.assertNotEqual(one.root,two.root)
        Path(one.scenes[0]['path']).write_text('one');one.save()
        Path(two.scenes[0]['path']).write_text('two')
        with self.assertRaises(RuntimeError):two.save()
        self.assertEqual(Path(two.scenes[0]['path']).read_text(),'two')
        self.assertTrue(two.conflict)

    def test_session_recovery_opens_unsaved_files_and_remembers_acknowledged_baseline(self):
        self.commit(self.a)
        def request(base,path,body,timeout):
            result=self.a._lapply(body['project_id'],body['base_revision'],body['scenes'],body['source'])
            return (409 if result.get('conflict') else 200),result
        from unittest.mock import patch
        with patch('mercury_session.Path.home',return_value=self.root):
            session=Session('local',self.a._lbundle('book-1'),request)
            Path(session.scenes[0]['path']).write_text('saved once');session.save()
            Path(session.scenes[0]['path']).write_text('unsaved after crash')
            record=json.loads((session.root/'session.json').read_text())
            record['bundle']['revision']={'revision_id':record['base_revision']}
            recovered=Session('local',record['bundle'],request,root=session.root)
        self.assertEqual(recovered.baseline['s1'],'saved once')
        self.assertEqual(recovered.scenes[0]['text'],'unsaved after crash')
        recovered.save()
        self.assertEqual(self.a._lproj('book-1')['chapters'][0]['scenes'][0]['text'],'unsaved after crash')

    def test_minimal_install_preserves_state_and_config(self):
        target=self.root/'installed';target.mkdir();config=target/'mercury_config.json';config.write_text('{"sync_enabled": true}')
        (target/'state').mkdir();(target/'state/current.mercury').write_text('keep')
        install(ROOT,target,self.root/'bin')
        self.assertEqual(config.read_text(),'{"sync_enabled": true}')
        self.assertEqual((target/'state/current.mercury').read_text(),'keep')
        result=subprocess.run([str(self.root/'bin/mercury'),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('recover',result.stdout)


class EditorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('nvim'),'Neovim not installed')
    def test_neovim_has_two_manuscript_rows_and_shared_scene_buffer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);scene=root/'scene.md';scene.write_text('original')
            session=root/'desk.json';session.write_text(json.dumps({'split':True,'initial':1,'scenes':[
                {'path':str(scene),'chapter_index':0,'scene_index':0,'scene_title':'One'}]}))
            result=subprocess.run(['nvim','--headless','-u','NONE','-i','NONE','-n',
                '-c','lua dofile(vim.env.MERCURY_DESK_LUA)',
                '-c',"lua assert(#vim.api.nvim_list_wins()==4); vim.api.nvim_buf_set_lines(0,0,-1,false,{'changed'}); vim.cmd('write'); vim.fn.writefile({vim.inspect(vim.fn.winlayout())},vim.env.MERCURY_LAYOUT)",
                '-c','qa!'],env=dict(os.environ,MERCURY_SESSION=str(session),MERCURY_DESK_LUA=str(ROOT/'mercury_desk.lua'),MERCURY_LAYOUT=str(root/'layout')),capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn('Error',result.stderr)
            self.assertEqual(scene.read_text(),'changed\n')
            layout=(root/'layout').read_text()
            self.assertIn('"col"',layout)
            self.assertEqual(layout.count('"row"'),2)

    def test_mini_editor_split_navigation_shared_scene_and_save(self):
        import mercury_desk
        from unittest.mock import patch
        keys=iter(['i','A','\x1b','\x17','\n','\t','j','\n','i','B','\x1b','\x13','\x11'])
        class Window:
            def getmaxyx(self):return (30,100)
            def erase(self):pass
            def keypad(self,*args):pass
            def timeout(self,*args):pass
            def addnstr(self,*args):pass
            def move(self,*args):pass
            def refresh(self):pass
            def get_wch(self):return next(keys)
        scenes=[dict(scene_id='s1',chapter_title='One',scene_title='First',chapter_index=0,scene_index=0,text=''),
                dict(scene_id='s2',chapter_title='Two',scene_title='Second',chapter_index=1,scene_index=0,text='')]
        saved=[];checkpoints=[]
        with patch.object(mercury_desk.curses,'wrapper',side_effect=lambda fn:fn(Window())),patch.object(mercury_desk.curses,'raw'),patch.object(mercury_desk.curses,'curs_set'):
            mercury_desk.run(scenes,lambda rows:checkpoints.append(rows),lambda:saved.append(True) or 'Saved')
        self.assertEqual([row['text'] for row in checkpoints[-1]],['A','B'])
        self.assertEqual(saved,[True])
    def test_undo_redo_and_unicode_selection(self):
        buffer=Buffer('héllo 世界');buffer.replace(6,8,'world')
        self.assertEqual(buffer.text,'héllo world');buffer.restore();self.assertEqual(buffer.text,'héllo 世界')
        buffer.restore(True);self.assertEqual(buffer.text,'héllo world')

    def test_wrapping_preserves_source_offsets_and_blank_lines(self):
        text='hello world\n\n世界 end';rows=wrapped(text,6)
        self.assertIn((12,12),rows)
        self.assertEqual(move_vertical('abc\ndef',2,1,8),6)
        self.assertEqual(rows[-1][1],len(text))


if __name__=='__main__':unittest.main()
