import copy
import curses
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

    def test_unchanged_legacy_autosave_does_not_create_revision_or_conflict(self):
        first=self.commit(self.a)
        project=copy.deepcopy(self.p);project['modified']='later clock value only'
        result=self.commit(self.a,project,parent='stale-browser-parent')
        self.assertFalse(result['saved']);self.assertEqual(result['revision'],first['revision'])
        self.assertEqual(len(list(self.a._lf('book-1','revisions').glob('*.json'))),1)

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
        self.assertEqual(Path(handler.translate_path('/?project=book-1')).name,'Mercury_Writer_1_6_8.html')
        for path in ['/mercury_server.py','/library/library.json','/../README.md','/%2e%2e/README.md']:
            self.assertEqual(Path(handler.translate_path(path)).name,'.missing-public-resource')

    def test_clipboard_endpoint_is_local_explicit_and_reads_only_saved_look_clips(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        import mercury_desk,sqlite3
        shelf=Mock();shelf.rows.return_value=[(7,'Saved writing excerpt')]
        look=SimpleNamespace(Shelf=Mock(return_value=shelf),TEXT_LIMIT=256000,sqlite3=sqlite3,read_clipboard=Mock())
        handler=self.a.Handler.__new__(self.a.Handler);handler.path='/api/clipboard';handler.client_address=('127.0.0.1',1)
        handler.headers={'Host':'127.0.0.1:8765','X-Mercury-Clipboard':'1','Sec-Fetch-Site':'same-origin'};handler.send_json=Mock()
        with patch.object(mercury_desk,'look_clipboard',return_value=look):handler._do_GET()
        handler.send_json.assert_called_once_with({'available':True,'clips':[{'id':7,'text':'Saved writing excerpt'}]})
        look.read_clipboard.assert_not_called();shelf.close.assert_called_once();shelf.set.assert_not_called()
        for headers in [{'Host':'attacker.example','X-Mercury-Clipboard':'1'},
                        {'Host':'127.0.0.1:8765'},
                        {'Host':'127.0.0.1:8765','X-Mercury-Clipboard':'1','Origin':'https://attacker.example'},
                        {'Host':'127.0.0.1:8765','X-Mercury-Clipboard':'1','Sec-Fetch-Site':'cross-site'}]:
            handler.headers=headers;handler.send_json.reset_mock()
            with patch.object(mercury_desk,'look_clipboard',side_effect=AssertionError('Do not read clips')):handler._do_GET()
            self.assertEqual(handler.send_json.call_args.args[1],403)

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
    def load_cli(self):
        import importlib.machinery
        loader=importlib.machinery.SourceFileLoader('mercury_cli_for_test',str(ROOT/'mercury'))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        cli=importlib.util.module_from_spec(spec);loader.exec_module(cli)
        return cli

    def test_library_editor_options_work_directly_and_after_subcommands(self):
        from unittest.mock import Mock,patch
        cli=self.load_cli();cli.library=Mock();cli.edit=Mock()
        cases=[([],None,False),(['--editor','Mini'],'mini',False),
               (['--editor','nvim-desk','--split'],'nvim-desk',True),
               (['library','--editor','Nvim'],'nvim',False),
               (['--editor','mini','library'],'mini',False)]
        for args,editor,split in cases:
            with self.subTest(args=args),patch.object(sys,'argv',['mercury',*args]):cli.main()
            cli.library.assert_called_with(editor,split)
        with patch.object(sys,'argv',['mercury','edit','Book','--editor','Mini']):cli.main()
        cli.edit.assert_called_once_with('Book',None,'mini',False)

    def test_mini_is_default_and_explicit_or_environment_editor_still_wins(self):
        from unittest.mock import Mock,patch
        cli=self.load_cli();cli.req=Mock(return_value=(200,{'scenes':[]}));cli.Session=Mock()
        with patch.dict(os.environ,{},clear=True):
            cli.edit_project('local',{'project_id':'book'})
            cli.Session.return_value.edit.assert_called_with('mini',False,None)
        with patch.dict(os.environ,{'MERCURY_EDITOR':'nvim'}):
            cli.edit_project('local',{'project_id':'book'})
            cli.Session.return_value.edit.assert_called_with('nvim',False,None)
            cli.edit_project('local',{'project_id':'book'},editor='mini',split=True)
            cli.Session.return_value.edit.assert_called_with('mini',True,None)

    def test_library_selection_preserves_editor_and_requested_split(self):
        from unittest.mock import Mock,patch
        cli=self.load_cli()
        cli.discover=Mock(return_value=('local',{'projects':[{'project_id':'book','title':'Book'}]}))
        cli.edit_project=Mock(return_value={'changed':0});cli.req=Mock(return_value=(200,{'projects':[]}))
        window=Mock();window.getmaxyx.return_value=(24,100);window.getch.side_effect=[10,ord('q')]
        with patch.object(cli.curses,'curs_set'),patch.object(cli.curses,'endwin'):
            cli.library_ui(window,'mini',False)
        cli.edit_project.assert_called_once_with('local',{'project_id':'book','title':'Book'},editor='mini',split=False)

    def test_neovim_option_uses_chapter_tree_and_personal_config(self):
        from unittest.mock import Mock,patch
        with tempfile.TemporaryDirectory() as temporary, patch('mercury_session.Path.home',return_value=Path(temporary)):
            scenes=[{'chapter_index':0,'chapter_title':'First chapter','scene_index':0,'scene_title':'Arrival','scene_id':'s1','text':'First draft'},
                    {'chapter_index':1,'chapter_title':'Second chapter','scene_index':0,'scene_title':'Departure','scene_id':'s2','text':'Another scene'}]
            request=Mock(return_value=(200,{'changed':1,'revision':{'revision_id':'r2'}}))
            session=Session('local',{'project_id':'book','scenes':scenes},request)
            self.assertEqual(Path(session.scenes[0]['path']).relative_to(session.root).as_posix(),'manuscript/01-First-chapter/01-Arrival.md')
            def edit(command,env):
                self.assertEqual(command,['/usr/bin/nvim',str(session.root/'manuscript')])
                self.assertIsNone(env)
                Path(session.scenes[1]['path']).write_text('Edited in another chapter')
                return Mock(returncode=0)
            with patch('mercury_session.shutil.which',return_value='/usr/bin/nvim'),patch('mercury_session.subprocess.run',side_effect=edit):
                session.edit('nvim')
            self.assertEqual(request.call_args.args[2]['scenes'],[{'scene_id':'s2','text':'Edited in another chapter'}])

    def test_native_neovim_split_and_custom_desk_are_separate_options(self):
        from unittest.mock import Mock,patch
        with tempfile.TemporaryDirectory() as temporary, patch('mercury_session.Path.home',return_value=Path(temporary)):
            scenes=[{'chapter_index':0,'chapter_title':'Chapter','scene_index':i,'scene_title':title,'scene_id':str(i),'text':title} for i,title in enumerate(['One','Two'])]
            session=Session('local',{'project_id':'book','scenes':scenes},Mock())
            with patch('mercury_session.shutil.which',return_value='/usr/bin/nvim'),patch('mercury_session.subprocess.run',return_value=Mock(returncode=0)) as launch:
                session.edit('nvim',split=True)
                self.assertEqual(launch.call_args.args[0],['/usr/bin/nvim','-o',session.scenes[0]['path'],session.scenes[1]['path']])
                session.edit('nvim-desk')
                self.assertIn('NONE',launch.call_args.args[0])
                self.assertIn('MERCURY_DESK_LUA',launch.call_args.kwargs['env'])

    def test_legacy_numbered_workspace_can_still_be_recovered(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'0001.md').write_text('Unsaved legacy draft')
            bundle={'project_id':'book','scenes':[{'chapter_index':0,'chapter_title':'Chapter','scene_index':0,'scene_title':'Scene','scene_id':'s1','text':'Saved draft'}]}
            session=Session('local',bundle,Mock(),root=root)
            self.assertEqual(Path(session.scenes[0]['path']),root/'0001.md')
            self.assertEqual(session.scenes[0]['text'],'Unsaved legacy draft')
            self.assertEqual(session.baseline['s1'],'Saved draft')

    def test_cli_open_shows_library_without_a_terminal_project_prompt(self):
        import importlib.machinery
        from unittest.mock import Mock,patch
        loader=importlib.machinery.SourceFileLoader('mercury_cli_for_test',str(ROOT/'mercury'))
        spec=importlib.util.spec_from_loader(loader.name,loader);cli=importlib.util.module_from_spec(spec);loader.exec_module(cli)
        cli.discover=lambda:('http://127.0.0.1:8765',{'projects':[{'project_id':'one'},{'project_id':'two'}]})
        cli.pick=Mock(side_effect=AssertionError('No terminal picker should open'))
        opened=Mock()
        with patch.object(cli.webbrowser,'open',opened),patch.object(sys,'argv',['mercury','open']):cli.main()
        opened.assert_called_once_with('http://127.0.0.1:8765/?library=1')
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
        with patch.object(mercury_desk.curses,'wrapper',side_effect=lambda fn:fn(Window())),patch.object(mercury_desk.curses,'raw'),patch.object(mercury_desk.curses,'curs_set'),patch.object(mercury_desk,'read_key',side_effect=lambda window:window.get_wch()):
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


class MiniWritingTests(unittest.TestCase):
    def test_pane_keys_decode_without_losing_modifiers(self):
        import mercury_desk as desk
        from unittest.mock import Mock,patch
        for sequence,action in [('\x17','toggle'),('\x1bW','focus'),('\x1b[119;4u','focus'),
                                ('\x1b[119;6u','close'),('\x1b[119;7u','close'),
                                ('\x1b\x17','close'),('\x1b[27;6;119~','close')]:
            window=Mock();window.get_wch.side_effect=list(sequence)
            self.assertEqual(desk.pane_action(desk.read_key(window)),action)
        self.assertIsNone(desk.pane_action('W'))
        with patch.dict(os.environ,{'KITTY_WINDOW_ID':'test'}),patch.object(desk.sys,'stdout') as output:
            output.isatty.return_value=True
            desk.mini_terminal_scope(True);desk.mini_terminal_scope(False)
            self.assertEqual([call.args[0] for call in output.write.call_args_list],
                             ['\x1b]1337;SetUserVar=mercury_mini=MQ==\x07','\x1b]1337;SetUserVar=mercury_mini\x07'])

    def test_close_keeps_other_view_only_keeps_focused_view(self):
        from mercury_desk import change_panes
        for focused in (0,1):
            for action,keep in [('close',1-focused),('only',focused),('toggle',1-focused)]:
                panes=[dict(scene=0,cursor=4,scroll=2,nav=0),dict(scene=1,cursor=8,scroll=6,nav=1)]
                retained=panes[keep].copy()
                state=dict(pane=focused,split=True,mode='VISUAL',command='x',shift_selection=True)
                change_panes(state,panes,action)
                self.assertEqual(panes[0],retained)
                self.assertEqual((state['pane'],state['split'],state['mode'],state['command'],state['shift_selection']),
                                 (0,False,'NORMAL','',False))
                change_panes(state,panes,'close')
                self.assertEqual(panes[0],retained)

    def test_modified_pane_keys_do_not_insert_escape_fragments(self):
        text,_=self.run_keys('', ['i','A','\x17','i','B','\x1b[119;4u','i','C',
                                 '\x1b[119;6u','i','D','\x1b[119;7u','i','E','\x11'])
        # Each view retains its own cursor while editing the same scene buffer.
        self.assertEqual(text,'CADEB')

    def test_pane_help_and_footer_expose_current_actions(self):
        from mercury_terminal import mini_bindings,mini_help
        hints=dict(mini_bindings(dict(mode='INSERT',split=True)))
        self.assertEqual(hints['Option/Alt-Shift-W'],'pane')
        self.assertEqual(hints['Ctrl-Shift-W'],'close pane')
        help_text=str(mini_help())
        for key in ('Ctrl-Option/Alt-W',':close',':sp',':scene [title]',':chapter [title]'):
            self.assertIn(key,help_text)

    def run_keys(self,text,keys,height=24,width=100):
        import mercury_desk
        from unittest.mock import patch
        frames=[];checkpoints=[];keys=iter(keys)
        class Window:
            cursor=None
            def getmaxyx(self):return height,width
            def erase(self):pass
            def keypad(self,*args):pass
            def timeout(self,*args):pass
            def addnstr(self,*args):pass
            def move(self,*position):self.cursor=position
            def refresh(self):pass
            def get_wch(self):frames.append(self.cursor);return next(keys)
        scenes=[dict(scene_id='one',chapter_title='Chapter',scene_title='Scene',chapter_index=0,scene_index=0,text=text)]
        with patch.object(mercury_desk.curses,'wrapper',side_effect=lambda fn:fn(Window())),patch.object(mercury_desk.curses,'raw'),patch.object(mercury_desk.curses,'curs_set'),patch.object(mercury_desk,'read_key',side_effect=lambda window:window.get_wch()):
            mercury_desk.run(scenes,lambda rows:checkpoints.append(rows),lambda:'Saved')
        return checkpoints[-1][0]['text'],frames

    def test_shift_select_copy_cut_and_system_paste_in_insert_mode(self):
        import mercury_desk
        from unittest.mock import patch
        with patch.object(mercury_desk,'clipboard_copy',return_value=(True,True)) as copy,patch.object(mercury_desk,'clipboard_paste',return_value='HI'):
            text,_=self.run_keys('hello world',['i']+[mercury_desk.curses.KEY_SRIGHT]*5+['\x03','\x18','\x16','\x11'])
        self.assertEqual(text,'HI world')
        self.assertEqual([call.args[0] for call in copy.call_args_list],['hello','hello'])

    def test_shift_selection_typing_replaces_selected_text(self):
        import mercury_desk
        text,_=self.run_keys('hello',['i',mercury_desk.curses.KEY_SRIGHT,mercury_desk.curses.KEY_SRIGHT,'Z','\x11'])
        self.assertEqual(text,'Zllo')

    def test_visual_mode_and_internal_register_work_without_desktop_clipboard(self):
        import mercury_desk
        from unittest.mock import patch
        with patch.object(mercury_desk,'clipboard_copy',return_value=(False,False)) as copy,patch.object(mercury_desk,'clipboard_paste',return_value=None):
            text,_=self.run_keys('héllo',['v','l','d','\x16','\x11'])
        copy.assert_called_once_with('hé')
        self.assertEqual(text,'héllo')

    def test_select_all_cut_preserves_entire_unicode_and_multiline_text(self):
        import mercury_desk
        from unittest.mock import patch
        original='世界\nsecond paragraph\n'
        with patch.object(mercury_desk,'clipboard_copy',return_value=(False,True)) as copy:
            text,_=self.run_keys(original,['\x01','\x18','\x11'])
        copy.assert_called_once_with(original);self.assertEqual(text,'')

    def test_page_navigation_preserves_cursor_screen_position_and_home_end(self):
        import mercury_desk
        keys=['i']+[curses.KEY_DOWN]*3+[curses.KEY_RIGHT]*4+[curses.KEY_NPAGE,curses.KEY_PPAGE,'\x1b[1;5F','\x1b[1;5H','\x11']
        original='\n'.join(['abcdefghij']*60)
        text,frames=self.run_keys(original,keys)
        self.assertEqual(text,original)
        self.assertEqual(frames[8],frames[9]);self.assertEqual(frames[8],frames[10])
        self.assertEqual(frames[-1],(1,25))

    def test_vertical_navigation_remembers_column_across_short_rows(self):
        text,frames=self.run_keys('abcdefghij\nx\nabcdefghij',['i']+[curses.KEY_RIGHT]*5+[curses.KEY_DOWN,curses.KEY_DOWN,'\x11'])
        self.assertEqual(frames[6][1],frames[8][1]);self.assertEqual(text,'abcdefghij\nx\nabcdefghij')

    def test_shift_end_and_control_shift_end_select_exclusive_ranges(self):
        import mercury_desk
        from unittest.mock import patch
        with patch.object(mercury_desk,'clipboard_copy',return_value=(True,True)) as copy:
            self.run_keys('first\nsecond',['\x1b[1;6F','\x03','\x11'])
        copy.assert_called_once_with('first\nsecond')

    def test_look_copy_records_explicit_text_without_enabling_capture(self):
        import mercury_desk,sqlite3
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        shelf=Mock();shelf.observe.return_value=True
        look=SimpleNamespace(copy_clipboard=Mock(return_value=True),read_clipboard=Mock(return_value='Shared text'),Shelf=Mock(return_value=shelf),sqlite3=sqlite3)
        with patch.object(mercury_desk,'look_clipboard',return_value=look):
            self.assertEqual(mercury_desk.clipboard_copy('Writing excerpt'),(True,True))
            self.assertEqual(mercury_desk.clipboard_paste(),'Shared text')
        shelf.observe.assert_called_once_with('Writing excerpt');shelf.close.assert_called_once();shelf.set.assert_not_called()

    def test_look_shelf_insertion_returns_to_editor(self):
        import mercury_desk
        from unittest.mock import patch
        with patch.object(mercury_desk,'clipboard_history',return_value='Saved clip'),patch.object(mercury_desk,'look_clipboard',return_value=object()):
            text,_=self.run_keys('draft',['i','\x02','\x11'])
        self.assertEqual(text,'Saved clipdraft')

    def test_navigation_decodes_terminfo_and_ansi_modified_keys(self):
        from mercury_desk import navigation_key
        self.assertEqual(navigation_key(curses.KEY_SLEFT),'shift-left')
        for code,name in [('\x1b[1;2A','shift-up'),('\x1b[1;5H','ctrl-home'),('\x1b[1;6F','ctrl-shift-end'),('\x1b[5~','pageup'),('\x1b[6;2~','shift-pagedown')]:
            self.assertEqual(navigation_key(code),name)

    def test_escape_reader_preserves_the_next_printable_key(self):
        from mercury_desk import read_key,INPUT_TIMEOUT_MS
        from unittest.mock import Mock,patch
        window=Mock();window.get_wch.side_effect=['\x1b','i']
        with patch.object(curses,'unget_wch') as put_back:
            self.assertEqual(read_key(window),'\x1b');put_back.assert_called_once_with('i')
        window.timeout.assert_called_with(INPUT_TIMEOUT_MS)
        window.get_wch.side_effect=['\x1b','[','1',';','2','D']
        self.assertEqual(read_key(window),'\x1b[1;2D')

    def test_help_preserves_insert_mode_and_shift_selection(self):
        text,_=self.run_keys('draft',['i','A',curses.KEY_F1,curses.KEY_F1,'B','\x11'])
        self.assertEqual(text,'ABdraft')
        text,_=self.run_keys('hello',['i',curses.KEY_SRIGHT,curses.KEY_F1,curses.KEY_F1,'Z','\x11'])
        self.assertEqual(text,'Zello')

    def test_question_mark_help_and_inserted_question_mark_are_distinct(self):
        text,_=self.run_keys('draft',['?','q','i','?','\x11'])
        self.assertEqual(text,'?draft')

    def test_soft_wrap_boundary_and_display_columns(self):
        from mercury_desk import move_vertical,row_at,wrapped
        self.assertEqual(row_at(wrapped('abcdefgh',4),4),1)
        self.assertEqual(move_vertical('世界ab\n123456',3,1,20),10)


class TerminalHintTests(unittest.TestCase):
    def test_palette_uses_multiple_roles_and_explicit_readable_text_colors(self):
        from mercury_terminal import terminal_theme
        from unittest.mock import patch
        with patch.object(curses,'has_colors',return_value=True),patch.object(curses,'start_color'),patch.object(curses,'COLORS',256,create=True),patch.object(curses,'COLOR_PAIRS',256,create=True),patch.object(curses,'init_pair') as init,patch.object(curses,'color_pair',side_effect=lambda index:index<<8):
            theme=terminal_theme()
        self.assertNotEqual(theme['selected'],theme['navigation'])
        self.assertNotIn(-1,init.call_args_list[0].args[1:])
        self.assertEqual(len({theme['normal'],theme['insert'],theme['visual'],theme['key']}),1)

    @unittest.skipUnless(os.name=='posix','Requires a real curses terminal')
    def test_quit_needs_no_enter_after_returning_from_mini(self):
        import fcntl,pty,select,struct,termios,time
        with tempfile.TemporaryDirectory() as temporary:
            script=Path(temporary)/'nested.py'
            script.write_text('import sys,importlib.machinery\nsys.path.insert(0,'+repr(str(ROOT))+')\nimport mercury_desk\nc=importlib.machinery.SourceFileLoader("cli",'+repr(str(ROOT/'mercury'))+').load_module()\nc.discover=lambda:("local",{"version":"LIBRARY_MARKER","projects":[{"project_id":"one","title":"Sample"}]})\nc.req=lambda *a,**k:(200,{"projects":[{"project_id":"one","title":"Sample"}]})\ndef edit(*a,**k):\n mercury_desk.run([dict(scene_id="one",chapter_title="Chapter",scene_title="Scene",chapter_index=0,scene_index=0,text="draft")],lambda rows:None,lambda:"Saved")\n return {"changed":0}\nc.edit_project=edit\nc.library()\nprint("EXITED",flush=True)\n')
            entry=Path(temporary)/'entry.txt'
            script.write_text(script.read_text().replace('c.library()\n','import termios\nfrom pathlib import Path\nPath('+repr(str(entry))+').write_text(repr(termios.tcgetattr(sys.stdin.fileno())))\nc.library()\n'))
            master,slave=pty.openpty();before=termios.tcgetattr(slave)
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,100,0,0))
            process=subprocess.Popen([sys.executable,str(script)],stdin=slave,stdout=slave,stderr=slave,env=dict(os.environ,TERM='xterm-256color'))
            output=b'';stage=0;canonical=None;deadline=time.monotonic()+5
            try:
                while time.monotonic()<deadline and process.poll() is None:
                    if select.select([master],[],[],.05)[0]:output+=os.read(master,65536)
                    if stage==0 and b'LIBRARY_MARKER' in output:os.write(master,b'\n');stage=1;output=b''
                    elif stage==1 and b'NORMAL' in output:os.write(master,b'\x11');stage=2;output=b''
                    elif stage==2 and b'SYNCED' in output:
                        canonical=bool(termios.tcgetattr(slave)[3]&termios.ICANON)
                        os.write(master,b'q');stage=3
                self.assertEqual(stage,3,output[-1000:])
                self.assertFalse(canonical,'Library must restore immediate key input after Mini')
                self.assertEqual(process.wait(timeout=1),0)
                import ast
                actual=termios.tcgetattr(slave);expected=ast.literal_eval(entry.read_text())
                # BSD may mark pending input for redisplay when canonical mode resumes.
                actual[3]&=~getattr(termios,'PENDIN',0);expected[3]&=~getattr(termios,'PENDIN',0)
                self.assertEqual(actual,expected)
            finally:
                if process.poll() is None:process.kill();process.wait()
                os.close(master);os.close(slave)

    def test_wrapped_bindings_preserve_all_keys_and_labels_at_narrow_widths(self):
        from mercury_terminal import binding_rows,cells
        bindings=[('Ctrl-S','save'),('Ctrl-B','LOOK clips'),('Shift+arrows','select'),('x','remove local copy'),('q','quit')]
        expected=''.join(key+label for key,label in bindings).replace(' ','')
        for width in (20,39,47,79,99):
            rows=binding_rows(bindings,width)
            self.assertTrue(all(cells(''.join(text for text,_ in row))<=width for row in rows))
            actual=''.join(text for row in rows for text,_ in row).replace(' ','')
            self.assertEqual(actual,expected)

    def test_mode_hints_include_clipboard_and_context_specific_actions(self):
        from mercury_terminal import mini_bindings
        for mode in ('NORMAL','INSERT','VISUAL','COMMAND'):
            bindings=dict(mini_bindings({'mode':mode,'tree':False}))
            self.assertEqual(bindings['Ctrl-B'],'clips');self.assertIn('F1',bindings)
            if mode=='INSERT':self.assertNotIn('Ctrl-J',bindings);self.assertNotIn('?',bindings)
        self.assertIn('Enter',dict(mini_bindings({'mode':'NORMAL','tree':True})))

    def test_key_and_description_attributes_differ_even_without_color(self):
        from mercury_terminal import hint_styles,binding_rows,paint_bindings
        from unittest.mock import Mock,patch
        with patch.object(curses,'has_colors',return_value=False):styles=hint_styles()
        self.assertNotEqual(styles[0],styles[1])
        window=Mock();paint_bindings(window,3,binding_rows([('Ctrl-B','clips')],40),styles)
        attrs=[call.args[4] for call in window.addnstr.call_args_list]
        self.assertIn(styles[0],attrs);self.assertIn(styles[1],attrs)

    def test_library_footer_wraps_without_overlapping_project_rows(self):
        from mercury_terminal import cells
        from unittest.mock import Mock,patch
        cli=EditorTests().load_cli();drawn=[]
        window=Mock();window.getmaxyx.return_value=(12,48);window.getch.return_value=ord('q')
        window.addnstr.side_effect=lambda row,col,text,limit,*args:drawn.append((row,col,text[:limit]))
        projects=[{'project_id':str(i),'title':'Project '+str(i)} for i in range(20)]
        cli.discover=Mock(return_value=('local',{'projects':projects}))
        with patch.object(curses,'curs_set'),patch.object(curses,'has_colors',return_value=False):cli.library_ui(window)
        for row,col,text in drawn:
            self.assertTrue(0<=row<12);self.assertLessEqual(col+cells(text),47)
        footers=[row for row,col,text in drawn if text=='↑↓']
        self.assertEqual(len(footers),1)
        project_rows=[row for row,col,text in drawn if text.startswith('  Project')]
        self.assertTrue(all(row<footers[0] for row in project_rows))
        self.assertTrue(any('quit' in text for _,_,text in drawn))


if __name__=='__main__':unittest.main()
