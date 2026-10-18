const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8');
function section(start, end) {
  const i = source.indexOf(start), j = source.indexOf(end, i);
  assert.ok(i >= 0 && j > i, `Missing section ${start}`);
  return source.slice(i, j);
}
function harness(reply = {status:200, body:{ready:true, mode:'test'}}, options = {}) {
  const elements = new Map();
  const $ = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      value:selector === '#apiBase' ? 'http://localhost:8080' : selector === '#apiKey' ? 'qa-only-key' : '',
      classList:{toggle(){},remove(){}}, textContent:'', disabled:false,
    });
    return elements.get(selector);
  };
  const calls = [];
  const dialogs = [];
  const context = {URL, AbortController, setTimeout, clearTimeout, $, console,
    location:{origin:'http://localhost:4173',protocol:'http:',hostname:'localhost'},
    ic:()=>'', toast:()=>{},renderUpload:()=>{},renderRules:()=>{},navigate:()=>{},$$:()=>[],
    clamp:(v,a,b)=>Math.min(b,Math.max(a,v)),openDialog:options=>dialogs.push(options),
    fetch:async(url, options)=>{calls.push({url,options});const current=typeof reply==='function'?await reply(url,options,calls.length):reply;return {
      ok:current.status>=200 && current.status<300,status:current.status,
      text:async()=>typeof current.body==='string'?current.body:JSON.stringify(current.body),
      json:async()=>current.body,
    };},
    ...options,
  };
  const esc = source.split('\n').find(line=>line.startsWith('const esc ='));
  const code = esc + '\n' + section('const SITE =', 'function releaseVideo(')
    + section('function normalizeMode(', 'function validateResult(')
    + section('function validateResult(', 'function renderRule(')
    + section('function renderRule(', 'function renderEvent(')
    + section('function renderEvent(', 'function selectEvent(')
    + section('function showVideo(', 'function syntheticFrame(')
    + '\n({request,getConnection,bootstrapLocalSession,checkReady,validateResult,modeBanner,renderRule,renderResults,renderReviewQuestions,renderAnalysisSummary,showVideo,poll,resumeJob,stopWork,state});';
  const api = vm.runInNewContext(code,context);
  return {api,calls,$,dialogs};
}

test('multipart upload targets the public Java API and lets fetch set its boundary', async()=>{
  const {api,calls}=harness({status:202,body:{job_id:'qa',status:'processing',mode:'test'}});
  const form=new FormData();form.append('file',new Blob(['fixture']), 'qa.mov');
  const result=await api.request('/api/v1/analyze',api.getConnection(),{method:'POST',body:form,expectedStatus:202});
  assert.equal(result.job_id,'qa');assert.equal(calls.length,1);
  assert.equal(calls[0].url,'http://localhost:8080/api/v1/analyze');
  assert.equal(calls[0].options.headers['X-API-Key'],'qa-only-key');
  assert.equal(calls[0].options.headers['Content-Type'],undefined);
  assert.equal(calls[0].options.body,form);
});

for (const [name,body,message] of [
  ['Java string error',{error:'Analysis service is not reachable'},'Analysis service is not reachable'],
  ['job error object',{error:{code:'TIMEOUT',message:'Analysis timed out'}},'Analysis timed out'],
  ['FastAPI detail',{detail:'invalid path'},'invalid path'],
]) test(name+' stays visible',async()=>{
  const {api}=harness({status:503,body});
  await assert.rejects(api.request('/readyz',api.getConnection()),error=>error.status===503 && error.message.includes(message));
});

test('unexpected upload HTTP 200 is rejected without a second POST',async()=>{
  const {api,calls}=harness({status:200,body:{job_id:'qa',status:'processing'}});
  await assert.rejects(api.request('/api/v1/analyze',api.getConnection(),{expectedStatus:202}),/202/);
  assert.equal(calls.length,1);
});

test('readiness in test mode is explicitly labelled',async()=>{
  const {api,$}=harness();await api.checkReady();
  assert.equal(api.state.ready,true);assert.equal(api.state.readyMode,'test');
  assert.match($('#readyStatus').textContent,/тестовом режиме/);
  assert.match($('#sidebarStatus').textContent,/тестовый/);
});
test('unknown readiness mode does not confirm a real model',async()=>{
  const {api,$}=harness({status:200,body:{ready:true}});await api.checkReady();
  assert.equal(api.state.readyMode,null);assert.match($('#readyStatus').textContent,/не подтверждено/);
});
test('ready false and unavailable service cannot mark the UI ready',async()=>{
  for(const response of [{status:200,body:{status:'ready',ready:false}},{status:503,body:{error:'Analysis service is not reachable'}}]) {
    const {api}=harness(response);await api.checkReady();assert.equal(api.state.ready,false);
  }
});
test('no_violation cannot contain events',()=>{
  const {api}=harness();
  assert.throws(()=>api.validateResult({job_id:'qa',status:'done',verdict:'no_violation',violations:[{}]}));
  assert.equal(api.validateResult({job_id:'qa',status:'done',verdict:'no_violation',violations:[]}).verdict,'no_violation');
});
test('failed job remains an error with no invented verdict',async()=>{
  const {api}=harness({status:200,body:{job_id:'qa',status:'failed',mode:'test',error:{code:'ANALYSIS_UNAVAILABLE',message:'Analysis service is not available'}}});
  Object.assign(api.state,{jobId:'qa',phase:'processing',deadline:Date.now()+5000});
  await api.poll(api.getConnection(),api.state.generation,new AbortController().signal);
  assert.equal(api.state.phase,'error');assert.equal(api.state.result,null);
  assert.match(api.state.error,/not available/);
});
test('test results have a warning; rule links are escaped and checked',()=>{
  const {api}=harness();api.state.mode='test';api.state.phase='done';
  assert.match(api.modeBanner(),/TEST: тестовый режим/);
  assert.match(api.renderRule({source_url:'https://adilet.zan.kz/rus/docs/test',document:'Test'}),/href="https:\/\/adilet/);
  assert.doesNotMatch(api.renderRule({source_url:'javascript:alert(1)',document:'<script>bad</script>'}),/<script>|href=/);
});

function localResult(overrides={}) {
  return {job_id:'local-qa',status:'done',mode:'real',verdict:'no_violation',violations:[],
    analysis:{experimental:true,new_training:false,findings_status:'requires_review',complete:true,timeline_covered:true,
      sample_fps:2,window_seconds:8,stride_seconds:4,windows_total:3,windows_done:3,elapsed_sec:12.5,
      review_questions:[{type:'Пересчёт денег',timecode_sec:6.25,message:'На выбранных кадрах не виден пересчёт. Проверьте контекст.',status:'requires_review'}],
      limitations:['Редкая выборка может пропустить быстрое действие.'],actions:[]},...overrides};
}

test('completed empty findings use requested label and observations stay separate',()=>{
  const {api,$}=harness();
  Object.assign(api.state,{phase:'done',mode:'real',videoUrl:'blob:synthetic-local-only',result:api.validateResult(localResult())});
  api.renderResults();
  const html=$('#resultContent').innerHTML;
  assert.match(html,/Сигналов не найдено/);
  assert.doesNotMatch(html,/не гарантия отсутствия нарушений|Недостаточно данных/);
  assert.match(html,/Дополнительные наблюдения/);
  assert.match(html,/data-question-seek="0"/);
  assert.match(html,/00:06\.25/);
  assert.match(html,/Обработано фрагментов: 3 \/ 3/);
  assert.match(html,/Предобученная модель, без дообучения/);
  assert.match(html,/Обработка на сервере: 00:12\.5/);
  assert.equal($('#eventCount').textContent,0);
  assert.equal($('#eventCount').hidden,true);
  assert.doesNotMatch(html,/Нарушение не обнаружено|DEMO:|TEST:/);
});

test('possible findings use qualified heading and real mode does not mean a verified conclusion',()=>{
  const {api,$}=harness();
  const result=localResult({verdict:'violation',violations:[{type:'Деньги на столе',description:'Нужно проверить контекст.',timecode_sec:8,evidence_frames:[{timestamp_sec:8,image_base64:'/9j/AA=='}],rule:null}]});
  Object.assign(api.state,{phase:'done',mode:'real',result:api.validateResult(result)});
  api.renderResults();
  assert.match($('#resultContent').innerHTML,/Найден подозрительный эпизод/);
  assert.match(api.renderRule(null),/Нормативное основание требует проверки/);
  assert.equal($('#eventCount').textContent,1);
});

test('model questions and limitations are escaped instead of interpreted as HTML',()=>{
  const {api,$}=harness();
  const result=localResult();
  result.analysis.review_questions[0].type='<script>unsafe</script>';
  result.analysis.review_questions[0].message='<img src=x onerror="unsafe()">';
  result.analysis.limitations=['<svg onload="unsafe()">'];
  Object.assign(api.state,{phase:'done',mode:'real',result:api.validateResult(result)});
  api.renderResults();
  const html=$('#resultContent').innerHTML;
  assert.match(html,/&lt;script&gt;unsafe&lt;\/script&gt;/);
  assert.match(html,/&lt;img src=x onerror=&quot;unsafe\(\)&quot;&gt;/);
  assert.match(html,/&lt;svg onload=&quot;unsafe\(\)&quot;&gt;/);
  assert.doesNotMatch(html,/<script>|<img src=x|<svg onload/);
  assert.doesNotMatch(html,/data-question-seek=/);
});

test('incomplete coverage cannot become an empty successful result',()=>{
  const {api}=harness();
  for (const patch of [{complete:false},{timeline_covered:false},{windows_done:2},{windows_done:4},{sample_fps:-1}]) {
    const result=localResult();Object.assign(result.analysis,patch);
    assert.throws(()=>api.validateResult(result),/Повреждённый результат/);
  }
});

test('experimental analysis must explicitly confirm full nonempty coverage',()=>{
  const {api}=harness();
  for (const key of ['complete','timeline_covered','windows_done','windows_total']) {
    const result=localResult();delete result.analysis[key];
    assert.throws(()=>api.validateResult(result),/Повреждённый результат/);
  }
  const empty=localResult();Object.assign(empty.analysis,{windows_done:0,windows_total:0});
  assert.throws(()=>api.validateResult(empty),/Повреждённый результат/);
});

test('malformed question timestamps and oversized or non-text lists are rejected',()=>{
  const {api}=harness();
  for (const patch of [{timecode_sec:-1},{timecode_sec:'6.25'},{timecode_sec:Infinity},{message:{}},{type:''}]) {
    const result=localResult();Object.assign(result.analysis.review_questions[0],patch);
    assert.throws(()=>api.validateResult(result),/Повреждённый результат/);
  }
  for(const limitations of ['not an array',[{}],Array(101).fill('limit')]) {
    const result=localResult();result.analysis.limitations=limitations;
    assert.throws(()=>api.validateResult(result),/Повреждённый результат/);
  }
});

test('question timestamp opens the same local video even with zero findings',()=>{
  const {api,dialogs}=harness();
  Object.assign(api.state,{mode:'real',videoUrl:'blob:synthetic-local-only',result:localResult()});
  api.showVideo(6.25);
  assert.equal(dialogs.length,1);assert.match(dialogs[0].desc,/00:06\.25/);
  const listeners={};const video={duration:20,addEventListener:(name,fn)=>listeners[name]=fn,pause(){},removeAttribute(){},load(){}};
  dialogs[0].onMount({querySelector:()=>video},{});listeners.loadedmetadata();
  assert.equal(video.src,'blob:synthetic-local-only');assert.equal(video.currentTime,6.25);
  api.showVideo(-1);api.showVideo(NaN);
  assert.equal(dialogs.length,1);
});

test('coarse windows label event and question time as approximate while frame time stays exact',()=>{
  const {api,$,dialogs}=harness();
  const result=localResult({verdict:'violation',violations:[{type:'Деньги на столе',description:'Проверьте фрагмент.',timecode_sec:8,evidence_frames:[{timestamp_sec:8.5,image_base64:'/9j/AA=='}],rule:null}]});
  result.analysis.localization='approximate_window';
  Object.assign(api.state,{phase:'done',mode:'real',videoUrl:'blob:synthetic-local-only',result:api.validateResult(result)});
  api.renderResults();
  const html=$('#resultContent').innerHTML, detail=$('#eventDetail').innerHTML;
  assert.match(html,/Примерное время событий/);
  assert.match(html,/не на точное начало действия/);
  assert.match(html,/≈ 00:08/);assert.match(html,/≈ 00:06\.25/);
  assert.match(detail,/Примерное время/);assert.match(detail,/≈ 00:08/);
  assert.match(detail,/data-frame-seek="0"/);assert.match(detail,/>00:08\.5<\/button>/);
  assert.doesNotMatch(detail,/≈ 00:08\.5/);
  api.showVideo();assert.match(dialogs[0].desc,/Примерное время 00:08/);
  api.showVideo(8.5,false);assert.match(dialogs[1].desc,/Отметка 00:08\.5/);assert.doesNotMatch(dialogs[1].desc,/Примерное/);
});

function fakeTimers() {
  const pending=new Map();let next=0;
  return {pending,setTimeout:(fn,delay)=>{pending.set(++next,{fn,delay});return next;},clearTimeout:id=>pending.delete(id)};
}

test('transient polling error recovers automatically using the same job and never repeats upload',async()=>{
  const timers=fakeTimers();
  const {api,calls,$}=harness((url,options,count)=>count===1
    ? {status:503,body:{error:'Temporary outage'}}
    : {status:200,body:{job_id:'qa',status:'done',mode:'real',verdict:'no_violation',violations:[]}},timers);
  Object.assign(api.state,{jobId:'qa',phase:'processing',deadline:Date.now()+5000});
  await api.poll(api.getConnection(),api.state.generation,new AbortController().signal);
  assert.equal(api.state.phase,'processing');assert.equal(api.state.pollErrors,1);
  assert.match($('#resultContent').innerHTML,/Восстанавливаем автоматически/);
  const scheduled=timers.pending.get(api.state.timer);timers.pending.delete(api.state.timer);
  await scheduled.fn();
  assert.equal(api.state.phase,'done');assert.equal(api.state.pollErrors,0);
  assert.equal(calls.length,2);assert.ok(calls.every(c=>c.options.method==='GET' && c.url.endsWith('/jobs/qa')));
  assert.match($('#resultContent').innerHTML,/Сигналов не найдено/);
});

test('repeated network failures stop after three retries with recoverable job and no success label',async()=>{
  const timers=fakeTimers();
  const {api,calls,$}=harness(()=>{throw new TypeError('Network error');},timers);
  Object.assign(api.state,{jobId:'qa',phase:'processing',deadline:Date.now()+20000});
  const signal=new AbortController().signal;
  await api.poll(api.getConnection(),api.state.generation,signal);
  for(let retry=0;retry<3;retry++) {
    const scheduled=timers.pending.get(api.state.timer);timers.pending.delete(api.state.timer);
    await scheduled.fn();
  }
  assert.equal(calls.length,4);assert.equal(api.state.phase,'paused');assert.equal(api.state.jobId,'qa');
  assert.equal(timers.pending.size,0);assert.equal(api.state.result,null);
  assert.match($('#resultContent').innerHTML,/Запросить статус/);
  assert.doesNotMatch($('#resultContent').innerHTML,/Сигналов не найдено|Найден подозрительный эпизод/);
});

test('deadline ends polling without a request or invented result',async()=>{
  const {api,calls,$}=harness();
  Object.assign(api.state,{jobId:'qa',phase:'processing',deadline:Date.now()-1});
  await api.poll(api.getConnection(),api.state.generation,new AbortController().signal);
  assert.equal(api.state.phase,'paused');assert.equal(api.state.result,null);assert.equal(calls.length,0);
  assert.match($('#resultContent').innerHTML,/За 5 минут/);
  assert.doesNotMatch($('#resultContent').innerHTML,/Сигналов не найдено|Найден подозрительный эпизод/);
});

test('malformed result pauses immediately without retrying or displaying success',async()=>{
  const timers=fakeTimers();
  const {api,calls,$}=harness({status:200,body:{job_id:'qa',status:'done',verdict:'no_violation',violations:[{}]}},timers);
  Object.assign(api.state,{jobId:'qa',phase:'processing',deadline:Date.now()+20000});
  await api.poll(api.getConnection(),api.state.generation,new AbortController().signal);
  assert.equal(api.state.phase,'paused');assert.equal(calls.length,1);assert.equal(timers.pending.size,0);
  assert.match($('#resultContent').innerHTML,/Повреждённый результат/);
  assert.doesNotMatch($('#resultContent').innerHTML,/Сигналов не найдено/);
});

test('local bootstrap uses guarded same-origin endpoint and keeps key only in memory',async()=>{
  const key='local-bootstrap-test-key-123456789';
  const {api,calls,$}=harness({status:200,body:{api_key:key,mode:'real'}});
  $('#apiBase').value='';$('#apiKey').value='';
  await api.bootstrapLocalSession();
  assert.equal(calls.length,1);assert.equal(calls[0].url,'/local-session');
  assert.equal(calls[0].options.headers['X-Local-Bootstrap'],'1');
  assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.cache,'no-store');
  assert.equal($('#apiKey').value,key);assert.equal(api.state.ready,false);
  assert.doesNotMatch($('#connectionNoteText').textContent,new RegExp(key));
});

test('local bootstrap does not replace credentials or populate a custom API destination',async()=>{
  for (const customBase of ['', 'https://example.test']) {
    const {api,calls,$}=harness();$('#apiBase').value=customBase;$('#apiKey').value=customBase?'':'existing-key';
    await api.bootstrapLocalSession();assert.equal(calls.length,0);
  }
});
