"""Local-only Qwen loading; never sends video, images or text to an API."""
import os
from pathlib import Path
from model_inputs import clip_prompt, frame_paths

HERE=Path(__file__).resolve().parent
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                  HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1', WANDB_DISABLED='true',
                  TOKENIZERS_PARALLELISM='false')
import socket
def no_network(*args,**kwargs):
    raise RuntimeError('Network access is disabled during local inference/training')
socket.create_connection=no_network
socket.socket.connect=no_network
socket.socket.connect_ex=no_network

import torch
from PIL import Image
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig

PROMPT=('Кадры одной видеозаписи кассовой операции даны по порядку. '
        'Определи, видны ли признаки возможного нарушения кассовой дисциплины. '
        'Верни только JSON: {"verdict":"violation"} или {"verdict":"no_violation"}. '
        'Не делай выводов о личности людей или невидимых операциях в банковской системе.')

def load(max_pixels=65536, model_dir=None, precision='nf4'):
    if precision not in {'nf4','bf16'}:raise ValueError('Unsupported local inference precision')
    if not torch.cuda.is_available(): raise RuntimeError('CUDA is not available; do not silently train on CPU')
    folder=Path(model_dir).resolve() if model_dir is not None else HERE/'base'
    if not folder.is_dir(): raise ValueError('The local model directory does not exist')
    processor=AutoProcessor.from_pretrained(folder,local_files_only=True,trust_remote_code=False,
                                            min_pixels=4096,max_pixels=max_pixels)
    options={}
    if precision=='nf4':
        options['quantization_config']=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',
                                bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16,
                                llm_int8_skip_modules=['visual','lm_head'])
    model=Qwen3VLForConditionalGeneration.from_pretrained(folder,local_files_only=True,
        trust_remote_code=False,device_map={'':0},
        dtype=torch.bfloat16,attn_implementation='sdpa',**options)
    model.config.use_cache=False
    return model,processor

def messages(record, prompt=None):
    prompt = clip_prompt(record, PROMPT) if prompt is None else prompt
    content=[]
    for number, f in enumerate(record['frames'], 1):
        label = f'Image {number} (video time {f["time_sec"]:.2f} seconds):' if record.get('number_frames') else f'Кадр, {f["time_sec"]:.2f} с.'
        content += [{'type':'text','text':label}, {'type':'image'}]
    content += [{'type':'text','text':prompt}]
    return [{'role':'user','content':content}]

def encode(processor,record,answer=None,prompt=None,assistant_prefix=''):
    images=[]
    for path in frame_paths(record, HERE/'data'):
        with Image.open(path) as image: images.append(image.convert('RGB'))
    text=processor.apply_chat_template(messages(record,prompt),tokenize=False,add_generation_prompt=True)
    if assistant_prefix:
        if answer is not None:raise ValueError('Assistant prefix is only supported for inference')
        text+=assistant_prefix
    prefix=processor(text=[text],images=images,return_tensors='pt')
    if answer is None: return prefix.to('cuda')
    full=processor(text=[text+answer+processor.tokenizer.eos_token],images=images,return_tensors='pt')
    length=prefix['input_ids'].shape[1]
    assert torch.equal(full['input_ids'][0,:length],prefix['input_ids'][0]),'Chat template prefix changed'
    labels=full['input_ids'].clone(); labels[:,:length]=-100
    assert (labels!=-100).any()
    full['labels']=labels
    return full.to('cuda')

def answer_loss(model,batch):
    # Only materialize vocabulary logits for the assistant answer, not hundreds
    # of visual/prompt tokens. The entire visual context still participates.
    labels=batch['labels']; count=int((labels[0]!=-100).sum())
    inputs={key:value for key,value in batch.items() if key!='labels'}
    result=model(**inputs,logits_to_keep=count+1)
    logits=result.logits[0,:-1].float()
    assert logits.shape[0]==count
    return torch.nn.functional.cross_entropy(logits,labels[0,-count:])
