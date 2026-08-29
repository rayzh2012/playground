#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan a bounded Parquet shard range once for all registered aliases.

Outputs are small rebuildable derivatives. Raw source bytes are never mutated.
Every occurrence carries corpus/source-shard/row/character locators and context.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import ahocorasick
import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, list_repo_files


def load_registry(path: Path):
    rows=[]
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f,delimiter='\t'):
            alias=(r.get('alias') or '').strip()
            if alias:
                rows.append({
                    'canonical':(r.get('canonical_entity') or alias).strip(),
                    'alias':alias,
                    'entity_type':(r.get('entity_type') or 'UNKNOWN').strip(),
                    'notes':(r.get('notes') or '').strip(),
                })
    return rows


def build_automaton(registry):
    A=ahocorasick.Automaton()
    for i,r in enumerate(registry):
        # One alias must have one registry row. If duplicates exist, fail rather
        # than silently assigning one spelling to multiple identities.
        if r['alias'] in A:
            raise ValueError(f"duplicate alias in registry: {r['alias']}")
        A.add_word(r['alias'],(i,r))
    A.make_automaton()
    return A


def sha256(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def ordinal_from_path(path: str, corpus: str):
    name=Path(path).name
    if corpus=='literature':
        # literature_zh-00001-of-00233.parquet -> 1
        return int(name.split('-')[1])
    if corpus=='cwt':
        # ...partial-001553.parquet -> 1553
        return int(name.rsplit('-',1)[1].split('.')[0])
    raise ValueError(corpus)


def select_files(repo_id: str, corpus: str, start: int, end: int):
    files=list_repo_files(repo_id,repo_type='dataset')
    chosen=[]
    for p in files:
        if not p.endswith('.parquet'):
            continue
        try:
            n=ordinal_from_path(p,corpus)
        except Exception:
            continue
        if start <= n <= end:
            chosen.append((n,p))
    chosen.sort()
    expected=end-start+1
    if len(chosen)!=expected:
        got=[n for n,_ in chosen]
        raise RuntimeError(f"range {start}-{end}: expected {expected} shards, got {len(chosen)} ordinals={got[:20]}...{got[-20:]}")
    return chosen


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--corpus',choices=['literature','cwt'],required=True)
    ap.add_argument('--start',type=int,required=True)
    ap.add_argument('--end',type=int,required=True)
    ap.add_argument('--registry',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--context',type=int,default=80)
    args=ap.parse_args()

    if args.end < args.start:
        raise ValueError('end < start')
    cfg={
        'literature':('GCI-HOLD-0001','Geralt-Targaryen/Literature-zh'),
        'cwt':('GCI-HOLD-0002','Morton-Li/ChineseWebText2.0-HighQuality'),
    }[args.corpus]
    corpus_id,repo_id=cfg
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    registry=load_registry(Path(args.registry))
    automaton=build_automaton(registry)
    files=select_files(repo_id,args.corpus,args.start,args.end)

    occ_rows=[]
    shard_rows=[]
    total_counts=Counter()
    started=time.time()

    for seq,(ordinal,source_path) in enumerate(files,1):
        local=Path(hf_hub_download(repo_id=repo_id,repo_type='dataset',filename=source_path))
        pf=pq.ParquetFile(local)
        if 'text' not in pf.schema_arrow.names:
            raise RuntimeError(f"text column missing in {source_path}: {pf.schema_arrow.names}")
        rows_seen=0
        shard_counts=Counter()
        shard_occ=0
        for batch in pf.iter_batches(columns=['text'],batch_size=2048):
            for text in batch.column(0).to_pylist():
                rows_seen += 1
                if text is None:
                    continue
                s=str(text)
                for end_pos,(reg_i,r) in automaton.iter(s):
                    start_pos=end_pos-len(r['alias'])+1
                    c0=max(0,start_pos-args.context)
                    c1=min(len(s),end_pos+1+args.context)
                    occ_rows.append({
                        'corpus_id':corpus_id,
                        'shard_ordinal':ordinal,
                        'source_path':source_path,
                        'row_no':rows_seen,
                        'match_start':start_pos,
                        'match_end':end_pos+1,
                        'canonical_entity':r['canonical'],
                        'alias':r['alias'],
                        'entity_type':r['entity_type'],
                        'context':s[c0:c1].replace('\n',' '),
                    })
                    shard_counts[r['alias']] += 1
                    total_counts[r['alias']] += 1
                    shard_occ += 1
        if rows_seen != pf.metadata.num_rows:
            raise RuntimeError((source_path,rows_seen,pf.metadata.num_rows))
        shard_rows.append({
            'corpus_id':corpus_id,
            'shard_ordinal':ordinal,
            'source_path':source_path,
            'bytes':local.stat().st_size,
            'sha256':sha256(local),
            'rows':rows_seen,
            'row_groups':pf.metadata.num_row_groups,
            'occurrences':shard_occ,
            'alias_counts_json':json.dumps(dict(sorted(shard_counts.items())),ensure_ascii=False,sort_keys=True),
        })
        print(json.dumps({
            'progress':f'{seq}/{len(files)}','corpus':corpus_id,'ordinal':ordinal,
            'rows':rows_seen,'occurrences':shard_occ
        },ensure_ascii=False),flush=True)

    occ_schema=pa.schema([
        ('corpus_id',pa.string()),('shard_ordinal',pa.int32()),('source_path',pa.string()),
        ('row_no',pa.int64()),('match_start',pa.int32()),('match_end',pa.int32()),
        ('canonical_entity',pa.string()),('alias',pa.string()),('entity_type',pa.string()),('context',pa.string()),
    ])
    table=pa.Table.from_pylist(occ_rows,schema=occ_schema)
    pq.write_table(table,out/'occurrences.parquet',compression='zstd')

    with (out/'shard_summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['corpus_id','shard_ordinal','source_path','bytes','sha256','rows','row_groups','occurrences','alias_counts_json']
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(shard_rows)
    with (out/'term_totals.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(['corpus_id','canonical_or_alias','count'])
        for alias,count in sorted(total_counts.items()):
            w.writerow([corpus_id,alias,count])
    manifest={
        'schema_version':'GCI-REGISTRY-SCAN-1.0','corpus_id':corpus_id,'repo_id':repo_id,
        'range_start':args.start,'range_end':args.end,'shard_count':len(files),
        'registry_alias_count':len(registry),'occurrence_count':len(occ_rows),
        'raw_mutated':False,'elapsed_seconds':round(time.time()-started,3),
        'locator_contract':'corpus_id + shard_ordinal + source_path + row_no + match_start/match_end',
    }
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
