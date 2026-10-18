'use strict';
const $=id=>document.getElementById(id);
let videos=[],active=null,busy=false,requestId=0,lastSignature='',batchFinished=false;
function rememberedVideo(value){try{if(value!==undefined)localStorage.setItem('qwen-auto-video',value);else return localStorage.getItem('qwen-auto-video');}catch(_){}return null;}
const statusNames={pending:'В очереди',refinement_pending:'Уточнение',incomplete:'Неполный анализ',candidate_found:'Есть предположения',no_candidate:'Обработано',processing:'Обработка',possible_signs:'Возможные признаки',uncertain:'Недостаточно оснований',no_signs_detected:'Признаки не найдены',insufficient_evidence:'Недостаточно данных'};
const fmt=t=>`${Math.floor(t/60).toString().padStart(2,'0')}:${(t%60).toFixed(1).padStart(4,'0')}`;
async function api(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw Error('Не удалось получить ответ локального сервера.');return response.json();}
function renderList(){const term=$('search').value.toLowerCase();$('videoList').replaceChildren();for(const v of videos.filter(v=>v.filename.toLowerCase().includes(term))){const b=document.createElement('button');b.className='video-item'+(v.video_id===active?' active':'');b.type='button';const name=document.createElement('strong');name.textContent=v.filename;const state=document.createElement('small');state.textContent=statusNames[v.status]||'Обработка';b.append(name,state);b.onclick=()=>select(v.video_id);$('videoList').append(b);}}
function card(event,uncertain=false){const node=document.createElement('div');node.className='event'+(uncertain?' uncertain':'');const title=document.createElement('h3');title.textContent=event.type||'Возможное событие';const description=document.createElement('p');description.textContent=uncertain?'Неуверенный ответ Qwen: достаточность оснований пока не установлена.':event.description||'Признак отмечен локальной моделью.';const seek=document.createElement('button');seek.type='button';seek.className='timecode';seek.textContent=`${fmt(event.start_sec)} — ${fmt(event.end_sec)}`;seek.onclick=()=>{const video=$('video');const selectedRequest=requestId;const at=()=>{if(selectedRequest!==requestId)return;video.currentTime=event.timecode_sec;video.play().catch(()=>{});};if(video.readyState>=1)at();else video.addEventListener('loadedmetadata',at,{once:true});};node.append(title,seek,description);return node;}
function loading(show, result={}) {
  $('analysisLoading').hidden=!show;
  $('answerContent').hidden=show;
  $('answerPanel').setAttribute('aria-busy',String(show));
  if(!show)return;
  const refining=result.scan_complete===true;
  $('loadingTitle').textContent=result.status==='pending'?'Видео в очереди':refining?'Уточняем события':'Анализируем видео';
  $('loadingHint').textContent=result.status==='pending'?'Обработка начнётся автоматически.':refining?'Проверяем основания и таймкоды.':'Смотрим фрагменты и последовательность действий.';
  $('stageWatch').className=refining?'done':'current';
  $('stageRefine').className=refining?'current':'';
  const p=result.candidate_progress;
  const valid=p&&Number.isInteger(p.done)&&Number.isInteger(p.total)&&p.total>0&&p.done>=0&&p.done<=p.total;
  $('loadingCount').hidden=!valid;
  $('loadingCount').textContent=valid?`Проверено предполагаемых событий: ${p.done} из ${p.total}`:'';
}
function connectionIssue(message){
  lastSignature='';
  if(!$('analysisLoading').hidden){loading(false);$('answerTitle').textContent='Связь с анализатором прервана';$('answerText').textContent='Повторим запрос автоматически. Обработка на сервере могла продолжиться.';}
  $('error').textContent=message;
}
function renderResult(result){
  const signature=JSON.stringify([result,batchFinished]);if(signature===lastSignature)return;lastSignature=signature;
  const terminal=['incomplete','insufficient_evidence','failed','error'].includes(result.status)||batchFinished;
  const pending=!result.complete&&!terminal;
  $('resultBadge').textContent=statusNames[result.status]||'Обработка';
  loading(pending,result);$('events').replaceChildren();$('uncertain').replaceChildren();
  if(pending)return;
  $('answerTitle').textContent=result.complete?result.message:'Полный анализ не получен';
  $('answerText').textContent=result.complete?'Анализ и проверка оснований выполнены автоматически. Таймкоды привязаны к исходному видео.':'Это не означает, что операция правильная. Доступные предположения ниже требуют проверки.';
  $('events').replaceChildren(...(result.events||[]).map(e=>card(e)));
  if(result.uncertain_events?.length){const details=document.createElement('details');const label=document.createElement('summary');label.textContent=`Неуверенные предположения Qwen: ${result.uncertain_events.length}`;details.append(label,...result.uncertain_events.map(e=>card(e,true)));$('uncertain').append(details);}
}
async function select(id){const info=videos.find(v=>v.video_id===id);if(!info)return;active=id;requestId++;const thisRequest=requestId;lastSignature='';rememberedVideo(id);loading(true);$('filename').textContent=info.filename;$('video').pause();$('video').src='/media/'+encodeURIComponent(id);$('mediaError').hidden=true;$('events').replaceChildren();$('uncertain').replaceChildren();$('resultBadge').textContent='Загрузка';$('answerTitle').textContent='Получение ответа Qwen…';$('answerText').textContent='Ответ появится здесь автоматически.';$('error').textContent='';renderList();try{const result=await api('/api/automatic/'+encodeURIComponent(id));if(thisRequest===requestId)renderResult(result);}catch(e){if(thisRequest===requestId)connectionIssue(e.message);}}
async function refresh(){if(busy)return;busy=true;try{const data=await api('/api/automatic');videos=data.videos;batchFinished=data.finished===true;$('batchStatus').textContent=`Просмотрено ${data.screened} из ${data.total} · Проверка событий завершена: ${data.completed} из ${data.total}`+ (data.finished?' · Пакет завершён':' · Обработка продолжается');$('batchProgress').max=Math.max(1,data.total);$('batchProgress').value=data.screened;renderList();$('error').textContent='';if(!active){const saved=rememberedVideo();await select(videos.some(v=>v.video_id===saved)?saved:videos[0]?.video_id);}else{const id=active;const thisRequest=requestId;try{const result=await api('/api/automatic/'+encodeURIComponent(id));if(thisRequest===requestId)renderResult(result);}catch(e){if(thisRequest===requestId)connectionIssue(e.message);}}}catch(e){connectionIssue(e.message);}finally{busy=false;}}
$('search').oninput=renderList;$('video').onerror=()=>{$('mediaError').hidden=false;};refresh();setInterval(refresh,4000);
