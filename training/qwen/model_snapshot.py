"""Read verified local download metadata without network or repeated weight hashing."""
import json
from pathlib import Path
import re


DEFAULT_FOLDER = Path(__file__).resolve().parent/'base'
MODEL_SIZES = {'Qwen/Qwen3-VL-2B-Instruct': 2048, 'Qwen/Qwen3-VL-4B-Instruct': 2560}


def snapshot_metadata(model_dir=None):
    """Require a completed downloader manifest for alternate model directories.

    The downloader verifies upstream hashes before marking its manifest complete.
    Here we validate structure, sizes and config; large weights are not rehashed.
    The pre-existing default 2B manifest predates the `complete` flag.
    """
    folder = (Path(model_dir) if model_dir is not None else DEFAULT_FOLDER).resolve()
    manifest = json.loads((folder/'download_manifest.json').read_text(encoding='utf-8'))
    legacy_default = folder == DEFAULT_FOLDER.resolve() and 'complete' not in manifest
    if not legacy_default and manifest.get('complete') is not True:
        raise ValueError('Local model download is not marked complete')
    repo, revision = manifest.get('repo'), manifest.get('revision')
    if repo not in MODEL_SIZES or not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('Local snapshot identity/revision is invalid')
    rows = manifest.get('files')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Local snapshot file manifest is empty')
    names = set()
    weights = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid snapshot file entry')
        name, size, sha = row.get('name'), row.get('size'), row.get('sha256')
        if (not isinstance(name, str) or not name or name in names or
                '/' in name or '\\' in name or ':' in name or Path(name).name != name):
            raise ValueError('Invalid or duplicate snapshot filename')
        names.add(name)
        file = folder/name
        if file.resolve().parent != folder:
            raise ValueError('Snapshot file resolves outside its model directory')
        if (type(size) is not int or size <= 0 or not isinstance(sha, str) or
                not re.fullmatch('[a-f0-9]{64}', sha)):
            raise ValueError('Invalid snapshot size/checksum metadata')
        if not file.is_file() or file.stat().st_size != size:
            raise ValueError('Local snapshot is missing a file or has a size mismatch')
        if name.endswith('.safetensors'):
            weights.add(name)
            if not legacy_default and row.get('upstream_sha256') != sha:
                raise ValueError('Alternate model weights lack verified upstream checksum metadata')
    if not {'config.json', 'tokenizer.json'} <= names or not weights:
        raise ValueError('Local snapshot does not contain config, tokenizer and weights')
    index_name = 'model.safetensors.index.json'
    if index_name in names:
        index = json.loads((folder/index_name).read_text(encoding='utf-8'))
        mapping = index.get('weight_map')
        if not isinstance(mapping, dict) or not mapping or set(mapping.values()) != weights:
            raise ValueError('Model shard index does not match the completed snapshot')
    elif weights != {'model.safetensors'}:
        raise ValueError('Sharded model is missing its index')
    config = json.loads((folder/'config.json').read_text(encoding='utf-8'))
    hidden_size = config.get('text_config', {}).get('hidden_size')
    if type(hidden_size) is not int or hidden_size != MODEL_SIZES[repo] or config.get('model_type') != 'qwen3_vl':
        raise ValueError('Model config does not match the downloaded snapshot identity')
    return {'model': repo.split('/')[-1], 'repo': repo, 'revision': revision,
            'hidden_size': hidden_size, 'folder': str(folder),
            'validation': 'download_manifest_and_file_sizes', 'legacy_default_manifest': legacy_default}
