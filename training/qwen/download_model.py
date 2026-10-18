"""Fetch official Qwen weights; no project data is read or uploaded."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib, json, urllib.request, urllib.parse, time

REPO='Qwen/Qwen3-VL-2B-Instruct'
REV='89644892e4d85e24eaac8bacfd4f463576704203'
DEST=Path(__file__).resolve().parent/'base'
DEST.mkdir(exist_ok=True)
entries=json.load(urllib.request.urlopen(f'https://huggingface.co/api/models/{REPO}/tree/{REV}',timeout=30))
selected=[e for e in entries if e['type']=='file' and (e['path'].endswith(('.json','.safetensors','.txt','.jinja')) or e['path'] in ['LICENSE','README.md'])]
def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
manifest={'repo':REPO,'revision':REV,'files':[]}
for entry in selected:
    name=entry['path']; assert '/' not in name
    file=DEST/name
    url=f'https://huggingface.co/{REPO}/resolve/{REV}/{urllib.parse.quote(name)}'
    expected=entry.get('lfs',{}).get('oid')
    if file.exists() and expected and sha(file)==expected:
        print('Already verified',name,flush=True)
    elif entry['size']<32*1024*1024:
        with urllib.request.urlopen(url,timeout=120) as r: file.write_bytes(r.read())
        assert file.stat().st_size==entry['size']
        if expected: assert sha(file)==expected
        print('Downloaded',name,flush=True)
    else:
        assert expected,'Large weight file has no official checksum'
        total=entry['size']; chunk=32*1024*1024
        parts=[(start,min(start+chunk,total)-1) for start in range(0,total,chunk)]
        def fetch(bounds):
            start,end=bounds; part=DEST/f'{name}.part.{start}'
            if part.exists() and part.stat().st_size==end-start+1: return
            for attempt in range(3):
                try:
                    req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
                    with urllib.request.urlopen(req,timeout=120) as r:
                        assert r.status==206 and r.headers['Content-Range']==f'bytes {start}-{end}/{total}'
                        with part.open('wb') as out:
                            while block:=r.read(1024*1024): out.write(block)
                    assert part.stat().st_size==end-start+1
                    return
                except Exception:
                    if attempt==2: raise
                    time.sleep(attempt+1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            for n,future in enumerate(as_completed([pool.submit(fetch,p) for p in parts]),1):
                future.result()
                if n%5==0 or n==len(parts): print(f'{name}: {n}/{len(parts)} chunks',flush=True)
        with file.open('wb') as out:
            for start,end in parts:
                with (DEST/f'{name}.part.{start}').open('rb') as f:
                    while block:=f.read(1024*1024): out.write(block)
        assert sha(file)==expected,'Weight checksum mismatch'
        for start,end in parts: (DEST/f'{name}.part.{start}').unlink()
        print('Verified',name,flush=True)
    manifest['files'].append({'name':name,'sha256':sha(file),'size':file.stat().st_size})
(DEST/'download_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Official Qwen snapshot verified. Ready for offline loading.',flush=True)
