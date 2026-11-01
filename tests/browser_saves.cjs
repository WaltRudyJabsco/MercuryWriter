// Exercise the shipped browser save functions with delayed server responses.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname,'../Mercury_Writer_1_6_0.html'),'utf8');
const source = html.slice(html.indexOf('function markDirty(){'),html.indexOf('function syncFromEditor(){'));

function setup() {
  const values = new Map(); const requests=[]; const timers=[];
  const project={project_id:'book-1',title:'Draft',chapters:[{scenes:[{id:'s1',title:'One',text:'original',target:100}]}]};
  const elements={'#editor':{value:'original'},'#titleInput':{value:'One'},'#sceneTarget':{value:'100'},'#saveState':{textContent:''}};
  const context={project,canonicalRevision:'r0',editGeneration:0,savedGeneration:0,
    applyingRemote:false,commitInFlight:false,serverCommitTimer:null,dirtyTimer:null,serverPollTimer:null,
    activeId:'s1',STORAGE:'project',document:{hidden:false},location:{search:''},URLSearchParams,
    console:{warn(){}},snapshots:[],toasts:[],newProjectId:()=> 'new-stable-id',localStorage:{setItem:(k,v)=>values.set(k,v),getItem:k=>values.get(k)||null,removeItem:k=>values.delete(k)},
    setTimeout:fn=>{timers.push(fn);return timers.length},clearTimeout(){},setInterval:()=>1,clearInterval(){},
    $:selector=>elements[selector], active:()=>context.project.chapters[0].scenes[0],
    snapshotCurrentProject:()=>context.snapshots.push(JSON.parse(JSON.stringify(context.project))),
    toast:message=>context.toasts.push(message),
    refreshAll:()=>{elements['#editor'].value=context.project.chapters[0].scenes[0].text},
    fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,reply:(body,status=200)=>resolve({ok:status<400,status,json:async()=>body})})),
  };
  // active() returns the same shape used by the actual browser scene model.
  context.active=()=>({scene:context.project.chapters[0].scenes[0]});
  vm.createContext(context);vm.runInContext(source,context);
  function edit(text) { elements['#editor'].value=text;context.project.chapters[0].scenes[0].text=text;context.markDirty(); }
  return {context,elements,values,requests,timers,edit};
}

(async()=>{
  {
    const {context:c,elements,values,requests,edit}=setup();
    const first=c.commitCanonical();assert.equal(requests.length,1);
    edit('typed while saving');requests[0].reply({revision:{revision_id:'r1'}});await first;
    assert.equal(c.canonicalRevision,'r1');assert.equal(elements['#editor'].value,'typed while saving');
    assert.ok(values.has('mercury_pending'));assert.ok(c.editGeneration>c.savedGeneration);
    const second=c.commitCanonical();
    const body=JSON.parse(requests[1].options.body);
    assert.equal(body.parent_revision,'r1');assert.equal(body.project.chapters[0].scenes[0].text,'typed while saving');
    requests[1].reply({revision:{revision_id:'r2'}});await second;
    assert.equal(c.savedGeneration,c.editGeneration);assert.ok(!values.has('mercury_pending'));
  }
  {
    const {context:c,requests,elements}=setup();delete c.project.project_id;c.canonicalRevision=null;
    const first=c.commitCanonical();assert.equal(JSON.parse(requests[0].options.body).project.project_id,'new-stable-id');
    requests[0].reply({project_id:'new-stable-id',revision:{revision_id:'r1'}});await first;
    elements['#editor'].value='next edit';c.project.chapters[0].scenes[0].text='next edit';c.markDirty();
    const second=c.commitCanonical();assert.equal(JSON.parse(requests[1].options.body).project.project_id,'new-stable-id');
    requests[1].reply({revision:{revision_id:'r2'}});await second;
  }
  {
    const {context:c,requests}=setup();const save=c.commitCanonical();
    c.project={project_id:'different-book',chapters:[{scenes:[{id:'new',text:'new manuscript'}]}]};
    c.canonicalRevision=null;c.markDirty();requests[0].reply({revision:{revision_id:'old-book-revision'}});await save;
    assert.equal(c.project.project_id,'different-book');assert.equal(c.canonicalRevision,null);
    assert.ok(c.editGeneration>c.savedGeneration);
  }
  {
    const {context:c,elements,requests,edit}=setup();
    const poll=c.pullCanonical();edit('typed while polling');
    requests[0].reply({project:{project_id:'book-1',chapters:[{scenes:[{id:'s1',text:'stale response'}]}]},revision:{revision_id:'other'}});
    await poll;assert.equal(elements['#editor'].value,'typed while polling');assert.equal(c.canonicalRevision,'r0');
  }
  {
    const {context:c,requests,values}=setup();
    values.set('mercury_pending',JSON.stringify({project_id:'book-1',base_revision:'offline-parent'}));
    c.canonicalRevision='unrelated-current';
    const boot=c.bootstrapCanonical();
    assert.equal(JSON.parse(requests[0].options.body).parent_revision,'offline-parent');
    requests[0].reply({revision:{revision_id:'offline-saved'}});
    await new Promise(resolve=>setImmediate(resolve));
    requests[1].reply({project:c.project,revision:{revision_id:'offline-saved'}});await boot;
    assert.equal(c.canonicalRevision,'offline-saved');
  }
  {
    const {context:c,requests}=setup();c.location.search='?project=missing-book';
    const boot=c.bootstrapCanonical();requests[0].reply({error:'missing'},404);await boot;
    assert.equal(c.project.project_id,'book-1');assert.equal(requests.length,1);
    assert.match(c.toasts[0],/not local yet/);
  }
  console.log('6 browser save/recovery race checks passed');
})().catch(error=>{console.error(error);process.exitCode=1});
