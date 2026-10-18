"""Local observation-first room-door decision; raw descriptions remain private."""
import json
import time

from native_video import encode_video


def door_observation_prompt(start, end):
    return (
        f'Observe the room access door in this video from {start:.3f} to {end:.3f} seconds. '
        'There is no presumed violation. Describe the actual door panel and opening at '
        'the beginning and end, then classify the visible sequence you described. '
        'A glass partition, safe, cabinet, counter opening or a person moving is not '
        'itself evidence of the room door state. Do not infer entry rights or identities. '
        'Return exactly one JSON object with keys "before", "after", "sequence", in that order. '
        'Before and after must be short visible observations (at most 12 words each, or "unclear"). '
        'For sequence use A if the identifiable room door stays closed; '
        'B if it opens for passage and then visibly closes; '
        'C if the identifiable room door remains open during continued activity without a visible later closure; '
        'D if its state or sequence cannot be reliably distinguished. '
        'A person can remain outside the threshold while a door stays open. '
        'Return only JSON, without Markdown.'
    )


def parse_door_observation(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ValueError('Duplicate door observation key')
            result[key]=value
        return result
    value=json.loads(text,object_pairs_hook=unique)
    if type(value) is not dict or set(value)!={'before','after','sequence'}:
        raise ValueError('Invalid door observation fields')
    if any(type(value[key]) is not str or not value[key].strip() or len(value[key])>250
           for key in ('before','after')):
        raise ValueError('Invalid door visual observation')
    if value['sequence'] not in ('A','B','C','D'):
        raise ValueError('Invalid door sequence')
    return value


def infer_door_observation(engine,frames,start,end,deadline):
    if time.monotonic()>=deadline-3:
        raise TimeoutError('Door observation deadline before encoding')
    pixels=min(3_145_728,getattr(engine,'pixel_cap',None) or 3_145_728)
    inputs=encode_video(engine.processor,frames,door_observation_prompt(start,end),max_total_pixels=pixels)
    count=inputs['input_ids'].shape[1]
    if time.monotonic()>=deadline-3:
        del inputs
        raise TimeoutError('Door observation deadline during encoding')
    with engine.torch.inference_mode():
        output=engine.model.generate(**inputs,max_new_tokens=140,do_sample=False,use_cache=True,
                                    stopping_criteria=engine.stopping(deadline-2))
    response=engine.processor.decode(output[0,count:],skip_special_tokens=True)
    trace={'response':response,'input_tokens':count,'frames':len(frames),
           'video_grid_thw':inputs['video_grid_thw'].tolist(),
           'effective_max_total_pixels':pixels,'answer_encoding':'free_door_observation_json'}
    del inputs,output
    if time.monotonic()>=deadline-2:
        raise TimeoutError('Door observation deadline during generation')
    return parse_door_observation(response),trace
