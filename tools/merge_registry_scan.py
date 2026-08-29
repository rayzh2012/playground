#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-root',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--expected-shards',type=int,required=True)
    args=ap.parse_args()
    root=Path(args.input_root)
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)

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
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        raise RuntimeError('no occurrence files')

    manifest={
        'schema_version':'GCI-REGISTRY-MERGE-1.0',
        'batch_count':len(manifests),
        'shard_count':len(summaries),
        'expected_shards':args.expected_shards,
        'occurrence_count':total_occ,
        'corpora':sorted(set(r['corpus_id'] for r in summaries)),
        'raw_mutated':False,
        'locator_contract':'corpus_id + shard_ordinal + source_path + row_no + match_start/match_end',
        'outputs':['registry_occurrences.parquet','shard_summary.csv','term_totals.csv'],
    }
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
