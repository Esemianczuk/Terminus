import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const appSource = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const workerSource = readFileSync(new URL('../web/service-worker.js', import.meta.url), 'utf8');
const OUTBOX = 'terminus.pending-events.v2';
const snapshot = () => ({ organism_id:'test-organism',revision:2,server_time:Date.now()/1000,behavior:'sleep',position:{x:.5,y:.5},nodes:[],edges:[],recent_events:[],learning:{},devices:[] });

// The app executes unchanged against a small, inert browser surface. Requests and
// browser storage are real boundary observations; no organism model is simulated.
class Element {
  constructor() {
    this.children=[]; this.dataset={}; this.style={setProperty(){}}; this.hidden=false; this.value=''; this.listeners=new Map();
    const classes=new Set();
    this.classList={add:(...items)=>items.forEach(item=>classes.add(item)),remove:(...items)=>items.forEach(item=>classes.delete(item)),contains:item=>classes.has(item),toggle:(item,value)=>{if(value??!classes.has(item))classes.add(item);else classes.delete(item);}};
  }
  querySelector(selector) { return this[selector] ||= new Element(); }
  addEventListener(name,handler) { this.listeners.set(name,handler); }
  setAttribute(key,value) { this[key]=value; }
  getAttribute(key) { return this[key]; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=[...items]; }
  focus() {}
  contains() { return false; }
  getBoundingClientRect() { return {width:1000,height:700,left:0,top:0}; }
  getContext() { return {setTransform(){}}; }
}

function browser(initialStorage={}) {
  const storage=new Map(Object.entries(initialStorage));
  const elements=new Map();
  const requests=[];
  const images=[];
  let sequence=0;
  let getStatus=200;
  const serverState=snapshot();
  storage.set('terminus.snapshot.v1',JSON.stringify({state:serverState,receivedAt:Date.now()}));
  const document={hidden:true,body:new Element(),querySelector(selector){if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);},createElement:()=>new Element(),createElementNS:()=>new Element(),addEventListener(){}};
  document.querySelector('#pairing').hidden=true;
  const context=vm.createContext({
    console,Date,Math,JSON,Map,Set,Number,String,Array,Object,Boolean,Promise,Error,AbortSignal,document,
    navigator:{onLine:false},location:{protocol:'http:',host:'127.0.0.1:8769'},window:{devicePixelRatio:1,addEventListener(){}},
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},
    crypto:{randomUUID:()=>`test-event-${++sequence}`},matchMedia:()=>({matches:false,addEventListener(){}}),ResizeObserver:class{observe(){}},Image:class{constructor(){this.listeners=new Map();images.push(this);}addEventListener(name,handler){this.listeners.set(name,handler);}},
    WebSocket:class{static CONNECTING=0;static OPEN=1;addEventListener(){} close(){}},
    requestAnimationFrame(){},setTimeout(){return 1;},clearTimeout(){},setInterval(){},
    fetch:async(url,options={})=>{
      const body=options.body?JSON.parse(options.body):undefined;
      requests.push({url,method:options.method||'GET',body});
      if(url==='/api/state')return {ok:getStatus===200,status:getStatus,json:async()=>serverState};
      // A duplicate acknowledgement is still a successfully delivered event.
      return {ok:true,status:200,json:async()=>({accepted:false,revision:2})};
    },
  });
  vm.runInContext(appSource,context);
  const run=source=>vm.runInContext(source,context);
  return {
    storage,requests,images,run,
    readOutbox:()=>JSON.parse(storage.get(OUTBOX)||'[]'),
    async offerContext(label){const input=document.querySelector('#context-input');input.value=label;const form=document.querySelector('#context-form');await form.listeners.get('submit')({preventDefault(){},currentTarget:form});},
    async reconnect(status=200){getStatus=status;run('navigator.onLine=true');await run('bootstrap()');await new Promise(resolve=>setImmediate(resolve));},
    element:selector=>document.querySelector(selector),
  };
}

test('a cached offline reload can queue an explicit context without claiming authentication or connection',async()=>{
  const client=browser();
  assert.equal(client.run('authenticated'),false);
  assert.equal(client.run('connected'),false);
  await client.offerContext('Offline continuity check');
  assert.equal(client.readOutbox().length,1);
  assert.equal(client.requests.length,0);
  assert.equal(client.element('#pairing').hidden,true);
  assert.equal(client.element('#connection').dataset.mode,'offline');
});

test('confirmed 401 blocks additions and upload until a fresh authenticated state arrives',async()=>{
  const client=browser();
  await client.offerContext('Before reconnect');
  await client.reconnect(401);
  await client.offerContext('Must not be queued');
  assert.equal(client.run('authenticated'),false);
  assert.equal(client.readOutbox().length,1);
  assert.equal(client.element('#pairing').hidden,false);
  assert.equal(client.requests.filter(request=>request.url==='/api/events').length,0);
  assert.equal(JSON.parse(client.storage.get('terminus.pairing-required')),true);
  await client.reconnect(200);
  assert.equal(client.requests.filter(request=>request.url==='/api/events').length,1);
  assert.equal(client.readOutbox().length,0);
});

test('replay preserves the event ID and strips internal metadata; stale clients cannot consume the v2 outbox',async()=>{
  const oldQueue=[{id:'old-event',kind:'context',context:'Old tab action',queuedAt:Date.now(),organismId:'test-organism'}];
  const client=browser({'terminus.pending-events.v1':JSON.stringify(oldQueue)});
  await client.offerContext('Current action');
  const pending=client.readOutbox()[0];
  assert.equal(pending.organismId,'test-organism');
  assert.equal(typeof pending.queuedAt,'number');
  await client.reconnect();
  const uploaded=client.requests.filter(request=>request.url==='/api/events');
  assert.equal(uploaded.length,1);
  assert.equal(uploaded[0].body.id,pending.id);
  assert.equal(uploaded[0].body.source,'manual');
  assert.equal('queuedAt' in uploaded[0].body,false);
  assert.equal('organismId' in uploaded[0].body,false);
  assert.equal(client.readOutbox().length,0,'duplicate acknowledgement drains the stable-ID action');
  assert.deepEqual(JSON.parse(client.storage.get('terminus.pending-events.v1')),oldQueue);
});

test('manual outbox is bounded, expires, and never replays to a different organism',async()=>{
  const client=browser();
  for(let index=0;index<25;index++)await client.offerContext(`Moment ${index}`);
  assert.equal(client.readOutbox().length,24);
  const entries=client.readOutbox();
  entries[0].queuedAt=Date.now()-31*60*1000;
  entries[1].organismId='different-organism';
  client.storage.set(OUTBOX,JSON.stringify(entries));
  await client.reconnect();
  const uploaded=client.requests.filter(request=>request.url==='/api/events');
  assert.equal(uploaded.length,22);
  assert.ok(uploaded.every(request=>request.body.id!==entries[0].id && request.body.id!==entries[1].id));
});

test('optional sleep art cannot replace the fallback until both aligned poses load',()=>{
  const client=browser();
  const refined=client.images.find(image=>image.src==='/assets/terminus-refined.png');
  const asleep=client.images.find(image=>image.src==='/assets/terminus-sleep.png');
  assert.equal(client.element('#creature').classList.contains('sleep-art-ready'),false);
  asleep.listeners.get('load')();
  assert.equal(client.element('#creature').classList.contains('sleep-art-ready'),false,'an unavailable base keeps the original fallback');
  refined.listeners.get('load')();
  assert.equal(client.element('#sprite').src,'/assets/terminus-refined.png');
  assert.equal(client.element('#sleep-sprite').src,'/assets/terminus-sleep.png');
  assert.equal(client.element('#creature').classList.contains('sleep-art-ready'),true);
  assert.equal(client.element('#creature').dataset.behavior,'sleep');
});

test('service worker caches the final shell/art and never intercepts API or authentication',async()=>{
  const handlers=new Map();
  const cached=[];
  const worker=vm.createContext({URL,Response,Promise,self:{location:{origin:'https://terminus.test'},addEventListener:(name,handler)=>handlers.set(name,handler),skipWaiting:async()=>{},clients:{claim:async()=>{}}},caches:{open:async()=>({addAll:async paths=>cached.push(...paths),add:async path=>cached.push(path)})}});
  vm.runInContext(workerSource,worker);
  let installation;
  handlers.get('install')({waitUntil:promise=>{installation=promise;}});
  await installation;
  for(const path of ['/index.html','/app.js','/styles.css','/assets/terminus-refined.png','/assets/terminus-sleep.png'])assert.ok(cached.includes(path));
  assert.ok(cached.every(path=>!path.startsWith('/api/')));
  for(const [path,method] of [['/api/state','GET'],['/api/inspect','GET'],['/api/pair','POST'],['/api/events','POST'],['/ws','GET']]) {
    let intercepted=false;
    handlers.get('fetch')({request:{url:`https://terminus.test${path}`,method},respondWith(){intercepted=true;}});
    assert.equal(intercepted,false,`${method} ${path} must stay outside the shell cache`);
  }
});
