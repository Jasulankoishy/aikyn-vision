"""Offline GPU worker: scans the entire timeline, saves AI candidates separately."""
from local_model import HERE,load,encode,torch
from temporal_core import windows,parse_events,merge_events
from sequence_core import VERSION,parse_actions,merge_actions,summarize,memory,action_prompt
from transformers import StoppingCriteria,StoppingCriteriaList
from pathlib import Path
import argparse,json,time,os,re,contextlib,hashlib
import av

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for retry in range(10):
        try: os.replace(temp,path);return
        except PermissionError:
            if retry==9: raise
            time.sleep(.03)

class Cancelled(Exception): pass
class StopOnCancel(StoppingCriteria):
    def __init__(self,path):self.path=path
    def __call__(self,input_ids,scores,**kwargs):return self.path.exists()

@contextlib.contextmanager
def gpu_lock():
    path=HERE/'temporal-gpu.lock'
    with path.open('a+b') as handle:
        handle.seek(0,2)
        if not handle.tell():handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)

def sample_video(path,folder,fps,cancel):
    folder.mkdir(parents=True,exist_ok=True);sampled=[];target=0.;last=None;last_time=None
    def save(frame,t):
        image=frame.to_image();image.thumbnail((768,768))
        destination=folder/f'{len(sampled):06}.jpg';image.save(destination,quality=92)
        sampled.append({'path':str(destination),'time_sec':round(t,6)})
    with av.open(str(path),options={'protocol_whitelist':'file'}) as container:
        stream=container.streams.video[0];origin=float((stream.start_time or 0)*stream.time_base)
        for frame in container.decode(stream):
            if cancel.exists():raise Cancelled()
            if frame.time is None or frame.is_corrupt:raise RuntimeError('Video contains invalid frames')
            t=float(frame.time)-origin
            if not math_finite(t) or t<0 or (last_time is not None and t<last_time):raise RuntimeError('Invalid frame timestamps')
            last,last_time=frame,t
            if t+1e-7>=target:
                save(frame,t)
                while target<=t+1e-7:target+=1/fps
        if last is None:raise RuntimeError('Empty video')
        if last_time>sampled[-1]['time_sec']+.01:save(last,last_time)
    return sampled

def math_finite(value):return value==value and abs(value)!=float('inf')

def run(job):
    spec=read(job/'request.json');cancel=job/'cancel';began=time.perf_counter()
    sequential=spec.get('analysis_mode')==VERSION
    if sequential:
        write(job/'implementation.json',{'mode':VERSION,'sha256':{
            name:hashlib.sha256((HERE/name).read_bytes()).hexdigest()
            for name in ['sequence_core.py','temporal_scan.py','local_model.py']}})
    status={'job_id':job.name,'state':'loading','video_count':len(spec['videos']),'videos_done':0,
            'windows_done':0,'unresolved_windows':0,'windows_total':sum(len(windows(v['duration_sec'])) for v in spec['videos']),
            'network_disabled':True,'model':'Qwen3-VL-2B-Instruct base','sample_fps':2,'window_seconds':8,'stride_seconds':4,'max_pixels_per_frame':147456,
            'analysis_mode':VERSION if sequential else 'independent-windows'}
    active=None
    def checkpoint():status['elapsed_seconds']=round(time.perf_counter()-began,1);write(job/'status.json',status)
    def publish():
        if active is None:return
        active['events']=merge_events(active['raw_events'])
        if sequential:
            active['actions']=merge_actions(active['raw_actions'])
            gaps=[{'start_sec':w['start_sec'],'end_sec':w['end_sec']} for w in active['windows'] if w['state']!='analyzed']
            active['sequence']=summarize(active['actions'],gaps)
        write(job/(active['video_id']+'.json'),active)
        write(Path(spec['latest_dir'])/(active['video_id']+'.json'),active)
    checkpoint()
    try:
        with gpu_lock():
            if cancel.exists():raise Cancelled()
            model,processor=load(max_pixels=147456);model.eval()
            model.generation_config.temperature=None;model.generation_config.top_p=None;model.generation_config.top_k=None
            taxonomy=[{'id':c['id'],'label':c['label'],'definition':c['definition'][:250]} for c in spec['categories']]
            # The request contains no organizer labels, per-video hypotheses or answer timecodes.
            category_text=json.dumps(taxonomy,ensure_ascii=False)
            category_ids={c['id'] for c in taxonomy}
            for item in spec['videos']:
                if cancel.exists():raise Cancelled()
                plan=windows(item['duration_sec']);status.update(state='sampling',video_id=item['video_id'],video_windows_total=len(plan),video_windows_done=0);checkpoint()
                active={'job_id':job.name,'video_id':item['video_id'],'state':'sampling','duration_sec':item['duration_sec'],
                        'sample_fps':2,'window_seconds':8,'stride_seconds':4,'timeline_covered':False,
                        'human_verified':False,'category_snapshot':spec['categories'],'raw_events':[], 'events':[], 'windows':[],
                        'limitations':['AI candidates only','Sampled frames may miss fast actions','Boundaries are approximate','Category rules require human verification']}
                if sequential:
                    active.update(analysis_mode=VERSION,raw_actions=[],actions=[],sequence=summarize([]))
                    active['limitations'] += ['Sequence memory is model-generated, not verified tracking',
                                              'Missing observation is not proof of omission',
                                              'Database writes require external local evidence']
                publish()
                frames=sample_video(Path(item['path']),job/'frames'/item['video_id'],2,cancel)
                if frames[-1]['time_sec']<item['duration_sec']-1:raise RuntimeError('Decoded video is shorter than the expected duration')
                active.update(state='scanning',sampled_frames=len(frames),last_sample_sec=frames[-1]['time_sec']);publish()
                for window in plan:
                    if cancel.exists():raise Cancelled()
                    selected=[f for f in frames if window['start_sec']<=f['time_sec']<=window['end_sec']]
                    if not selected:raise RuntimeError('No frames in planned window')
                    status.update(state='scanning',window_start_sec=window['start_sec'],window_end_sec=window['end_sec']);checkpoint()
                    numbered=' '.join(f'{i+1}={f["time_sec"]:.3f}s' for i,f in enumerate(selected))
                    prompt=('Review this bank-counter clip using only the ordered frames. Find up to TWO visible actions '
                            'that might match a category. Categories are provisional, not proven legal violations. '
                            'Do not identify people or invent hidden actions or contents of objects. '
                            'Missing actions between sampled frames cannot be ruled out. '
                            'Categories: '+category_text+'. Frame number to original video time: '+numbered+'. '
                            'Complete this JSON only: {"events":[],"uncertain":true,"observation":"short Russian sentence"}. '
                            'Each event must have exactly category_id (an ID from the list), first_frame (integer), '
                            'last_frame (integer), visible_action (Russian, MAXIMUM 12 words). '
                            'Frame numbers are 1-based indices, NOT seconds. first_frame <= last_frame. '
                            'Use events=[] when no visible evidence supports a category. Set uncertain=true when '
                            'context or visibility is insufficient. observation: MAXIMUM 15 Russian words describing visible actions. '
                            'No Markdown, no explanations outside JSON. End with a closing brace.')
                    if sequential:
                        context=memory(active['actions'],active['sequence'])
                        prompt=action_prompt(selected,context)
                        write(job/'contexts'/f'{item["video_id"]}-{window["index"]}.json',context)
                    outcome={'index':window['index'],'start_sec':window['start_sec'],'end_sec':window['end_sec'],
                             'sampled_timestamps':[f['time_sec'] for f in selected],'state':'invalid_response'}
                    for attempt in range(2):
                        prefix='{"actions":' if sequential else '{"events":'
                        retry=' STRICT limit: three actions, no descriptions, only the three required fields.' if sequential else ' STRICT limit: one event, 8 words per description.'
                        inputs=encode(processor,{'frames':selected},prompt=prompt+(retry if attempt else ''),assistant_prefix=prefix)
                        with torch.inference_mode():
                            output=model.generate(**inputs,max_new_tokens=600 if sequential else 360,do_sample=False,use_cache=True,
                                                  stopping_criteria=StoppingCriteriaList([StopOnCancel(cancel)]))
                        text=prefix+processor.decode(output[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True)
                        del inputs,output
                        if cancel.exists():raise Cancelled()
                        write(job/'responses'/f'{item["video_id"]}-{window["index"]}-{attempt}.json',{'text':text})
                        try:
                            if sequential:
                                uncertain,actions=parse_actions(text,selected,window)
                                outcome.update(state='analyzed',assessment='uncertain' if uncertain else 'actions_observed',
                                               action_count=len(actions),observation='; '.join(a['evidence'] for a in actions),
                                               prior_action_count=len(active['actions']))
                                outcome.pop('parse_error',None)
                                active['raw_actions'].extend(actions)
                                break
                            assessment,events=parse_events(text,selected,category_ids,window)
                            outcome.update(state='analyzed',assessment=assessment,event_count=len(events))
                            outcome.pop('parse_error',None)
                            parsed=json.loads(text[text.index('{'):text.rindex('}')+1]);observation=parsed.get('observation','')
                            outcome['observation']=observation[:1200] if isinstance(observation,str) else ''
                            active['raw_events'].extend(events);break
                        except ValueError as error:outcome['parse_error']=str(error)
                    active['windows'].append(outcome);status['windows_done']+=1;status['video_windows_done']+=1
                    if outcome['state']!='analyzed':status['unresolved_windows']+=1
                    publish();checkpoint();print(f'Processed {status["windows_done"]}/{status["windows_total"]} windows; content saved locally',flush=True)
                active['timeline_covered']=len(active['windows'])==len(plan)
                active['state']='completed' if all(w['state']=='analyzed' for w in active['windows']) else 'partial'
                publish();status['videos_done']+=1;checkpoint()
            status.update(state='partial' if status['unresolved_windows'] else 'completed',peak_vram_gib=round(torch.cuda.max_memory_allocated()/2**30,3));checkpoint()
    except Cancelled:
        if active:active['state']='cancelled';publish()
        status['state']='cancelled';checkpoint()
    except Exception as error:
        if active:active['state']='failed';publish()
        status.update(state='failed',error=str(error));checkpoint();raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);args=parser.parse_args()
    run(Path(args.job).resolve())
