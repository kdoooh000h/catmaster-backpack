"""Explicit local public-catalog encoder cache; no download or runtime install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def load_model(model_manifest):
    # All model files must already be present in the explicit task-owned path.
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
    from sentence_transformers import SentenceTransformer
    import torch
    manifest=json.loads(Path(model_manifest).read_text())
    return SentenceTransformer(manifest['snapshot'],local_files_only=True,
                               trust_remote_code=False,device='mps' if torch.backends.mps.is_available() else 'cpu')


def build(catalog,model_manifest,output,passage_prefix='',query_prefix=''):
    import numpy as np
    output=Path(output);output.mkdir(exist_ok=False,mode=0o700)
    rows=json.loads(Path(catalog).read_text());began=time.monotonic()
    model=load_model(model_manifest)
    manifest=json.loads(Path(model_manifest).read_text())
    texts=[passage_prefix+r['name']+'. '+r['description'] for r in rows]
    vectors=model.encode(texts,batch_size=128,normalize_embeddings=True,
                         show_progress_bar=True,convert_to_numpy=True)
    np.save(output/'vectors.npy',vectors)
    lock={'catalog_sha256':digest(catalog),'model':{k:v for k,v in manifest.items() if k!='snapshot'},
          'model_files':{str(p.relative_to(manifest['snapshot'])):digest(p)
                         for p in Path(manifest['snapshot']).rglob('*') if p.is_file()},
          'ids':[r['id'] for r in rows],'dimensions':list(vectors.shape),'max_seq_length':model.max_seq_length,
          'passage_prefix':passage_prefix,'query_prefix':query_prefix,'text':'name + period + description',
          'seconds':time.monotonic()-began,'device':str(model.device),'vectors_sha256':digest(output/'vectors.npy')}
    (output/'index.json').write_text(json.dumps(lock,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in lock.items() if k not in ['ids','model_files']}),flush=True)


def load(catalog,model_manifest,index_dir):
    import numpy as np
    from semantic_recall import SemanticIndex
    index=Path(index_dir);lock=json.loads((index/'index.json').read_text())
    rows=json.loads(Path(catalog).read_text());manifest=json.loads(Path(model_manifest).read_text())
    if lock['catalog_sha256']!=digest(catalog) or lock['ids']!=[r['id'] for r in rows]:raise ValueError('catalog_cache_mismatch')
    if digest(index/'vectors.npy')!=lock['vectors_sha256']:raise ValueError('vector_cache_mismatch')
    if any(digest(Path(manifest['snapshot'])/p)!=sha for p,sha in lock['model_files'].items()):raise ValueError('model_changed')
    model=load_model(model_manifest)
    return SemanticIndex(rows,np.load(index/'vectors.npy'),
          lambda qs:model.encode(qs,batch_size=32,normalize_embeddings=True,show_progress_bar=False),
          query_prefix=lock['query_prefix'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--catalog',required=True);p.add_argument('--model-manifest',required=True)
    p.add_argument('--output',required=True);p.add_argument('--passage-prefix',default='');p.add_argument('--query-prefix',default='')
    a=p.parse_args();build(a.catalog,a.model_manifest,a.output,a.passage_prefix,a.query_prefix)
