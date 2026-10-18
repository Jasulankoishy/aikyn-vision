"""Pure temporal planning and strict parsing; no model or network imports."""
import json,math

def windows(duration,size=8.,stride=4.):
    if not all(math.isfinite(v) and v>0 for v in [duration,size,stride]) or stride>size: raise ValueError('Invalid window configuration')
    result=[];start=0.
    while True:
        end=min(duration,start+size);result.append({'index':len(result),'start_sec':start,'end_sec':end})
        if end>=duration: return result
        start+=stride

def parse_events(text,frames,category_ids,window):
    try:
        value=json.loads(text[text.index('{'):text.rindex('}')+1])
    except (ValueError,TypeError) as error: raise ValueError('Model response is not complete JSON') from error
    events=value.get('events')
    if not isinstance(events,list) or len(events)>5: raise ValueError('Invalid events list')
    if 'uncertain' in value:
        if type(value['uncertain'])!=bool:raise ValueError('Uncertainty must be boolean')
        assessment='uncertain' if value['uncertain'] else ('candidates' if events else 'no_visible_candidate')
    else:
        assessment=value.get('assessment')
        if assessment not in {'candidates','no_visible_candidate','uncertain'}: raise ValueError('Missing assessment')
        if (assessment=='candidates')!=bool(events): raise ValueError('Assessment contradicts events')
    result=[]
    for event in events:
        if not isinstance(event,dict): raise ValueError('Invalid event')
        cid=event.get('category_id');a=event.get('first_frame');b=event.get('last_frame');action=event.get('visible_action')
        if cid not in category_ids: raise ValueError('Unknown category')
        if type(a)!=int or type(b)!=int or not 1<=a<=b<=len(frames): raise ValueError('Frame index outside window')
        if not isinstance(action,str) or not action.strip() or len(action)>600: raise ValueError('Missing or excessive evidence description')
        # A sampled support envelope, never a claim of exact action boundaries.
        start=max(window['start_sec'],frames[a-1]['time_sec']-.25)
        end=min(window['end_sec'],frames[b-1]['time_sec']+.25)
        if not start<end: raise ValueError('Empty support interval')
        result.append({'category_id':cid,'start_sec':round(start,3),'end_sec':round(end,3),
                       'visible_action':action.strip(),'status':'candidate','boundary_status':'approximate_sample_support',
                       'supporting_windows':[window['index']],
                       'evidence_timestamps':[f['time_sec'] for f in frames[a-1:b]]})
    return assessment,result

def merge_events(events):
    merged=[]
    for event in sorted(events,key=lambda e:(e['category_id'],e['start_sec'],e['end_sec'])):
        prev=merged[-1] if merged else None
        if prev and prev['category_id']==event['category_id'] and event['start_sec']<prev['end_sec']:
            prev['end_sec']=max(prev['end_sec'],event['end_sec'])
            prev['supporting_windows']=sorted(set(prev['supporting_windows']+event['supporting_windows']))
            prev['evidence_timestamps']=sorted(set(prev['evidence_timestamps']+event['evidence_timestamps']))
            if event['visible_action'] not in prev['visible_action']:
                prev['visible_action']=(prev['visible_action']+' / '+event['visible_action'])[:3500]
        else: merged.append({**event,'supporting_windows':list(event['supporting_windows']),'evidence_timestamps':list(event['evidence_timestamps'])})
    merged.sort(key=lambda e:e['start_sec'])
    for number,event in enumerate(merged,1): event['id']=f'e{number:03}'
    return merged
