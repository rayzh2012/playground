#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def safe_alias_filename(alias: str) -> str:
    # Current ancient-name registry aliases are filesystem-safe Unicode. Keep
    # them human-readable, but neutralize path/control characters defensively.
    bad='\\/:*?"<>|\x00\n\r\t'
    name=''.join('_' if ch in bad else ch for ch in alias).strip('. ')
    return (name or 'EMPTY') + '.parquet'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-root',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--expected-shards',type=int,required=True)
    args=ap.parse_args()
    root=Path(args.input_root)
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    by_alias=out/'by_alias'; by_alias.mkdir(exist_ok=True)

    manifests=[]
    summaries=[]
    occurrence_files=[]
    totals=Counter()
    for mpath in sorted(root.rglob('manifest.json')):
        d=mpath.parent
        manifest=json.loads(mpath.read_text(encoding='utf-8'))
        manifests.append(manifest)
        sp=d/'shard_summary.csv'
        tp=d/'term_totals.csv'
        op=d/'occurrences.parquet'
        if not (sp.exists() and tp.exists() and op.exists()):
            raise RuntimeError(f'incomplete batch {d}')
        with sp.open('r',encoding='utf-8-sig',newline='') as f:
            summaries.extend(csv.DictReader(f))
        with tp.open('r',encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                totals[(r['corpus_id'],r['canonical_or_alias'])]+=int(r['count'])
        occurrence_files.append(op)

    if len(summaries)!=args.expected_shards:
        raise RuntimeError(f'expected {args.expected_shards} shard summaries, got {len(summaries)}')
    keys=[(r['corpus_id'],int(r['shard_ordinal'])) for r in summaries]
    if len(keys)!=len(set(keys)):
        raise RuntimeError('duplicate shard summaries')

    summaries.sort(key=lambda r:(r['corpus_id'],int(r['shard_ordinal'])))
    with (out/'shard_summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['corpus_id','shard_ordinal','source_path','bytes','sha256','rows','row_groups','occurrences','alias_counts_json']
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(summaries)
    with (out/'term_totals.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(['corpus_id','alias','count'])
        for (corpus,alias),count in sorted(totals.items()):
            w.writerow([corpus,alias,count])

    writer=None
    alias_writers={}
    alias_meta=defaultdict(lambda:{'canonical':set(),'entity_type':set(),'rows':0})
    total_occ=0
    try:
        for p in occurrence_files:
            pf=pq.ParquetFile(p)
            for batch in pf.iter_batches(batch_size=65536):
                table=pa.Table.from_batches([batch])
                if writer is None:
                    writer=pq.ParquetWriter(out/'registry_occurrences.parquet',table.schema,compression='zstd')
                writer.write_table(table)
                total_occ += table.num_rows

                aliases=set(x for x in table.column('alias').to_pylist() if x is not None)
                for alias in aliases:
                    sub=table.filter(pc.equal(table.column('alias'),pa.scalar(alias)))
                    if sub.num_rows==0:
                        continue
                    if alias not in alias_writers:
                        alias_writers[alias]=pq.ParquetWriter(by_alias/safe_alias_filename(alias),sub.schema,compression='zstd')
                    alias_writers[alias].write_table(sub)
                    meta=alias_meta[alias]
                    meta['rows'] += sub.num_rows
                    meta['canonical'].update(x for x in sub.column('canonical_entity').to_pylist() if x)
                    meta['entity_type'].update(x for x in sub.column('entity_type').to_pylist() if x)
    finally:
        if writer is not None:
            writer.close()
        for aw in alias_writers.values():
            aw.close()
    if writer is None:
        raise RuntimeError('no occurrence files')

    with (out/'by_alias_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['alias','file','occurrence_rows','canonical_entities','entity_types'])
        for alias in sorted(alias_meta):
            meta=alias_meta[alias]
            w.writerow([
                alias,
                f'by_alias/{safe_alias_filename(alias)}',
                meta['rows'],
                '|'.join(sorted(meta['canonical'])),
                '|'.join(sorted(meta['entity_type'])),
            ])

    if sum(m['rows'] for m in alias_meta.values()) != total_occ:
        raise RuntimeError('per-alias partition row total does not equal merged occurrence total')

    manifest={
        'schema_version':'GCI-REGISTRY-MERGE-1.1',
        'batch_count':len(manifests),
        'shard_count':len(summaries),
        'expected_shards':args.expected_shards,
        'occurrence_count':total_occ,
        'alias_file_count':len(alias_meta),
        'corpora':sorted(set(r['corpus_id'] for r in summaries)),
        'raw_mutated':False,
        'locator_contract':'corpus_id + shard_ordinal + source_path + row_no + match_start/match_end',
        'outputs':['registry_occurrences.parquet','by_alias/','by_alias_index.csv','shard_summary.csv','term_totals.csv'],
    }
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
