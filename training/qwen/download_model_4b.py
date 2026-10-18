"""Download one pinned official Qwen 4B snapshot; never reads project media.

Only GET requests are made to Hugging Face and its download redirects. No model
code is executed. Large weights require the upstream LFS SHA-256 checksum.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request

REPO = 'Qwen/Qwen3-VL-4B-Instruct'
REVISION = 'ebb281ec70b05090aa6165b016eac8ec08e71b17'
DEST = Path(__file__).resolve().parent / 'base-4b'
API = f'https://huggingface.co/api/models/{REPO}'
WORKERS = 8
SMALL_NAMES = {
    'config.json', 'generation_config.json', 'preprocessor_config.json',
    'video_preprocessor_config.json', 'processor_config.json',
    'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
    'added_tokens.json', 'chat_template.json', 'chat_template.jinja',
    'vocab.json', 'merges.txt', 'model.safetensors.index.json',
    'LICENSE', 'LICENSE.txt', 'README.md',
}


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def save_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temp, path)


def get(url, timeout=120, headers=None):
    return urllib.request.urlopen(urllib.request.Request(
        url, headers={'User-Agent': 'local-qwen-snapshot-fetcher/1.0', **(headers or {})}), timeout=timeout)


def tree(revision):
    prefix = f'{API}/tree/{revision}'
    url = prefix + '?limit=1000'
    entries, visited = [], set()
    while url:
        if url in visited or not (url == prefix or url.startswith(prefix + '?')):
            raise RuntimeError('Unexpected or repeating model tree pagination URL')
        visited.add(url)
        with get(url, timeout=30) as response:
            page = json.load(response)
            link = response.headers.get('Link', '')
        if not isinstance(page, list):
            raise RuntimeError('Invalid model tree response')
        entries.extend(page)
        next_links = re.findall(r'<([^>]+)>;\s*rel="?next"?', link)
        if len(next_links) > 1:
            raise RuntimeError('Ambiguous model tree pagination')
        url = next_links[0] if next_links else None
    return entries


def selected_entries(entries):
    selected = []
    for entry in entries:
        name = entry.get('path', '')
        if entry.get('type') != 'file':
            continue
        if name not in SMALL_NAMES and not re.fullmatch(r'model(?:-\d{5}-of-\d{5})?\.safetensors', name):
            continue
        if Path(name).name != name or '/' in name or '\\' in name:
            raise RuntimeError('Unsafe upstream file path')
        size = entry.get('size')
        if type(size) is not int or size <= 0:
            raise RuntimeError('Invalid upstream file size')
        lfs_hash = entry.get('lfs', {}).get('oid')
        if name.endswith('.safetensors') and not re.fullmatch(r'[a-f0-9]{64}', lfs_hash or ''):
            raise RuntimeError('Weight file has no official SHA-256 checksum')
        selected.append(entry)
    names = {entry['path'] for entry in selected}
    if len(names) != len(selected) or not {'config.json', 'tokenizer.json'} <= names:
        raise RuntimeError('Incomplete or duplicate model snapshot')
    if not any(name.endswith('.safetensors') for name in names):
        raise RuntimeError('No safetensors weights in snapshot')
    return sorted(selected, key=lambda entry: (entry['path'].endswith('.safetensors'), entry['path']))


def validate(path, entry):
    if not path.is_file() or path.stat().st_size != entry['size']:
        return False
    expected = entry.get('lfs', {}).get('oid')
    if expected:
        return digest(path) == expected
    git_oid = entry.get('oid')
    if not re.fullmatch(r'[a-f0-9]{40}', git_oid or ''):
        raise RuntimeError('Small file has no upstream Git blob checksum')
    data = path.read_bytes()
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest() == git_oid


def fetch_small(url, file, entry):
    temp = file.with_name(file.name + '.download')
    for attempt in range(3):
        try:
            with get(url) as response, temp.open('wb') as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            if not validate(temp, entry):
                raise RuntimeError(f'Checksum mismatch: {file.name}')
            os.replace(temp, file)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def fetch_large(url, file, entry):
    total, chunk = entry['size'], 32 * 1024 * 1024
    ranges = [(start, min(start + chunk, total) - 1) for start in range(0, total, chunk)]

    def fetch(bounds):
        start, end = bounds
        part = DEST / f'{file.name}.part.{start}'
        if part.is_file() and part.stat().st_size == end - start + 1:
            return
        temp = part.with_name(part.name + '.download')
        for attempt in range(4):
            try:
                with get(url, headers={'Range': f'bytes={start}-{end}'}) as response:
                    expected_range = f'bytes {start}-{end}/{total}'
                    if response.status != 206 or response.headers.get('Content-Range') != expected_range:
                        raise RuntimeError('Server did not honor the requested byte range')
                    with temp.open('wb') as output:
                        shutil.copyfileobj(response, output, length=1024 * 1024)
                if temp.stat().st_size != end - start + 1:
                    raise RuntimeError('Incomplete byte range')
                os.replace(temp, part)
                return
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(attempt + 1)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for count, future in enumerate(as_completed([pool.submit(fetch, bounds) for bounds in ranges]), 1):
            future.result()
            if count % 5 == 0 or count == len(ranges):
                print(f'{file.name}: {count}/{len(ranges)} chunks', flush=True)
    assembled = file.with_name(file.name + '.assembled')
    with assembled.open('wb') as output:
        for start, _ in ranges:
            with (DEST / f'{file.name}.part.{start}').open('rb') as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    if not validate(assembled, entry):
        raise RuntimeError('Assembled weight checksum mismatch; partial files retained for diagnosis')
    os.replace(assembled, file)
    # Delete only our explicitly named, verified snapshot parts in this folder.
    for start, _ in ranges:
        (DEST / f'{file.name}.part.{start}').unlink()


def main():
    global WORKERS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=(8, 16), default=8)
    WORKERS = parser.parse_args().workers
    DEST.mkdir(exist_ok=True)
    (DEST / '.gitignore').write_text('*\n', encoding='utf-8')
    pin = DEST / 'snapshot_pin.json'
    if pin.is_file():
        pinned = json.loads(pin.read_text(encoding='utf-8'))
        if pinned.get('repo') != REPO or pinned.get('revision') != REVISION:
            raise RuntimeError('Existing snapshot differs from this published model revision')
        revision = pinned.get('revision', '')
    else:
        revision = REVISION
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise RuntimeError('Model API did not supply a valid immutable revision')
    save_json(pin, {'repo': REPO, 'revision': revision})
    entries = selected_entries(tree(revision))
    total = sum(entry['size'] for entry in entries)
    print(json.dumps({'repo': REPO, 'revision': revision, 'files': len(entries),
                      'total_bytes': total, 'workers': WORKERS}), flush=True)
    if shutil.disk_usage(DEST).free < total * 2 + 512 * 1024 * 1024:
        # Resume is allowed when all large weights are already present, but do
        # not begin a fresh weight download without assembly headroom.
        if not all((DEST / entry['path']).is_file() for entry in entries if entry['path'].endswith('.safetensors')):
            raise RuntimeError('Insufficient free disk space for download and verified assembly')
    manifest = {'repo': REPO, 'revision': revision, 'complete': False, 'files': []}
    save_json(DEST / 'download_manifest.json', manifest)
    for entry in entries:
        file = DEST / entry['path']
        url = f'https://huggingface.co/{REPO}/resolve/{revision}/{urllib.parse.quote(file.name)}'
        if validate(file, entry):
            print('Already verified', file.name, flush=True)
        else:
            (fetch_large if entry['size'] >= 32 * 1024 * 1024 else fetch_small)(url, file, entry)
            print('Verified', file.name, flush=True)
        manifest['files'].append({'name': file.name, 'size': file.stat().st_size,
                                  'sha256': digest(file), 'upstream_sha256': entry.get('lfs', {}).get('oid'),
                                  'upstream_git_oid': entry.get('oid')})
        save_json(DEST / 'download_manifest.json', manifest)
    index = DEST / 'model.safetensors.index.json'
    if index.is_file():
        shards = set(json.loads(index.read_text(encoding='utf-8'))['weight_map'].values())
        downloaded = {item['name'] for item in manifest['files']}
        if not shards or not shards <= downloaded:
            raise RuntimeError('Weight index references missing or unsafe shards')
    manifest['complete'] = True
    save_json(DEST / 'download_manifest.json', manifest)
    print(f'Official {REPO} snapshot verified. Ready for offline loading.', flush=True)


if __name__ == '__main__':
    main()
