"""New manuscript sections use the same recoverable revision boundary as text."""
import json
from pathlib import Path

import pytest
from mercury_session import Session
from test_mercury import server_at, manuscript


@pytest.fixture
def writing(tmp_path,monkeypatch):
    server=server_at(tmp_path/'server')
    server._lcommit(manuscript())
    def request(base,path,body,timeout):
        result=server._lapply(body['project_id'],body['base_revision'],body['scenes'],body['source'],body.get('additions'))
        return (409 if result.get('conflict') else 200),result
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    return server,Session('local',server._lbundle('book-1'),request),request


def test_new_scene_and_chapter_save_reopen_and_sync(writing,tmp_path):
    server,session,_=writing
    scene=session.add('scene','s1','The visitor')
    Path(scene['path']).write_text('A visitor arrives.')
    chapter=session.add('chapter',scene['scene_id'],'A new beginning')
    Path(chapter['path']).write_text('A fresh start.')
    session.save()
    project=server._lproj('book-1')
    assert [c['title'] for c in project['chapters']]==['One','A new beginning']
    assert [s['title'] for s in project['chapters'][0]['scenes']]==['Arrival','Departure','The visitor']
    assert project['chapters'][0]['scenes'][2]['text']=='A visitor arrives.'
    assert project['chapters'][1]['scenes'][0]['text']=='A fresh start.'
    assert not session.additions
    assert session.save()=='Saved · no pending edits'
    reopened=server._lbundle('book-1')
    assert len(reopened['scenes'])==4
    import mercury_sync
    peer=server_at(tmp_path/'peer')
    mercury_sync.configure(server,True);mercury_sync.configure(peer,True)
    mercury_sync.exchange(peer,mercury_sync.export(server))
    assert peer._lproj('book-1')['chapters']==project['chapters']


def test_offline_sections_recover_with_text_and_save_when_back_online(writing):
    server,session,request=writing
    def offline(*args):raise OSError('offline')
    session.request=offline
    chapter=session.add('chapter','s1')
    scene=session.add('scene',chapter['scene_id'])
    Path(scene['path']).write_text('Written while offline')
    with pytest.raises(OSError):session.save()
    record=json.loads((session.root/'session.json').read_text())
    record['bundle']['revision']={'revision_id':record['base_revision']}
    recovered=Session('local',record['bundle'],request,root=session.root)
    recovered.save()
    assert server._lproj('book-1')['chapters'][1]['scenes'][1]['text']=='Written while offline'
    assert len(server._lproj('book-1')['chapters'])==2


def test_concurrent_creation_preserves_conflict_and_local_scene(writing):
    server,session,_=writing
    addition=session.add('scene','s1')
    Path(addition['path']).write_text('My new scene')
    current=server._lproj('book-1');current['author']='Other editor'
    server._lcommit(current,server._lrev('book-1')['revision_id'])
    with pytest.raises(RuntimeError,match='Concurrent draft'):session.save()
    assert len(server._lproj('book-1')['chapters'][0]['scenes'])==2
    assert Path(addition['path']).read_text()=='My new scene'
    assert session.additions and session.conflict
    assert any(addition['scene_id'] in p.read_text() for p in server._lf('book-1','conflicts').glob('*.json'))


def test_lost_acknowledgement_retries_without_duplicate_sections(writing):
    server,session,request=writing
    session.add('chapter','s1')
    def lost(*args):
        request(*args)
        raise OSError('response lost')
    session.request=lost
    with pytest.raises(OSError):session.save()
    session.request=request
    session.save()
    assert len(server._lproj('book-1')['chapters'])==2
    assert not session.additions


def test_old_server_cannot_silently_discard_new_sections(writing):
    _,session,_=writing
    session.add('scene','s1')
    session.request=lambda *args:(200,{'changed':0})
    with pytest.raises(RuntimeError,match='server needs'):session.save()
    assert session.additions


def test_invalid_addition_does_not_change_head(writing):
    server,_,_=writing
    before=server._lbundle('book-1')
    for addition in [dict(kind='scene',chapter_id='missing'),dict(kind='chapter',chapter_id='c1'),dict(kind='chapter',chapter_id='new',scene_id='s1')]:
        with pytest.raises(ValueError):server._lapply('book-1',before['revision']['revision_id'],[],'test',[addition])
    assert server._lbundle('book-1')==before


def test_sidebar_and_command_creation_update_both_panes_without_losing_text(writing,monkeypatch):
    import mercury_desk as desk
    from unittest.mock import Mock
    server,session,_=writing
    # Create a scene from the sidebar, split, create a named chapter from command
    # mode in the other view, then return to the first view and continue writing.
    keys=iter(['\t','s','A','\x1b','\x17','\x1b[119;4u',':',*'chapter Finale','\r','B','\x1b','\x1b[119;4u','a','C','\x13','\x11'])
    window=Mock();window.getmaxyx.return_value=(36,120)
    monkeypatch.setattr(desk,'run_screen',lambda fn:fn(window))
    monkeypatch.setattr(desk.curses,'raw',lambda:None)
    monkeypatch.setattr(desk.curses,'curs_set',lambda *a:None)
    monkeypatch.setattr(desk,'read_key',lambda window:next(keys))
    desk.run(session.scenes,session.checkpoint,session.save,add=session.add)
    session.save()
    chapters=server._lproj('book-1')['chapters']
    assert chapters[0]['scenes'][2]['text']=='AC'
    assert chapters[1]['title']=='Finale'
    assert chapters[1]['scenes'][0]['text']=='B'
