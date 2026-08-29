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
    bad='\\/:*?"<>|\x00\n\r\t'
    name=''.join('_' if ch in bad else ch for ch in alias).strip('. ')
    return (name or 'EMPTY') + '.parquet'


def load_policy(path: Path):
    policy={}
    if not path.exists():
        return policy
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f,delimiter='\t'):
            alias=(r.get('alias') or '').strip()
            if not alias:
                continue
            substrings=[x for x in (r.get('hard_false_positive_substrings') or '').split('|') if x]
            policy[alias]={
                'precision_class':(r.get('precision_class') or 'UNCLASSIFIED').strip(),
                'hard_false_positive_substrings':substrings,
                'policy_note':(r.get('policy_note') or '').strip(),
            }
    return policy


def enrich_quality(table: pa.Table, policy: dict):
    aliases=table.column('alias').to_pylist()
    contexts=table.column('context').to_pylist()
    precision=[]; hard_fp=[]; fp_rule=[]
    for alias,ctx in zip(aliases,contexts):
        p=policy.get(alias or '',{})
        precision.append(p.get('precision_class','UNCLASSIFIED'))
        text=ctx or ''
        matched=''
        for s in p.get('hard_false_positive_substrings',[]):
            if s and s in text:
                matched=s; break
        hard_fp.append(bool(matched)); fp_rule.append(matched)
    return table.append_column('retrieval_precision',pa.array(precision,pa.string())) \
                .append_column('hard_false_positive',pa.array(hard_fp,pa.bool_())) \
                .append_column('hard_false_positive_rule',pa.array(fp_rule,pa.string()))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-root',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--expected-shards',type=int,required=True)
    ap.add_argument('--policy',default='corpus_index/alias_precision_policy.tsv')
    args=ap.parse_args()
    root=Path(args.input_root)
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    by_alias=out/'by_alias'; by_alias.mkdir(exist_ok=True)
    policy=load_policy(Path(args.policy))

    manifests=[]; summaries=[]; occurrence_files=[]; totals=Counter()
    for mpath in sorted(root.rglob('manifest.json')):
        d=mpath.parent
        manifest=json.loads(mpath.read_text(encoding='utf-8'))
        manifests.append(manifest)
        sp=d/'shard_summary.csv'; tp=d/'term_totals.csv'; op=d/'occurrences.parquet'
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
        w=csv.writer(f); w.writerow(['corpus_id','alias','raw_count'])
        for (corpus,alias),count in sorted(totals.items()):
            w.writerow([corpus,alias,count])

    raw_writer=None; research_writer=None; alias_writers={}
    alias_meta=defaultdict(lambda:{'canonical':set(),'entity_type':set(),'raw_rows':0,'research_rows':0,'hard_fp_rows':0})
    research_totals=Counter(); raw_total=0; research_total=0; hard_fp_total=0
    try:
        for p in occurrence_files:
            pf=pq.ParquetFile(p)
            for batch in pf.iter_batches(batch_size=65536):
                raw=pa.Table.from_batches([batch])
                if raw_writer is None:
                    raw_writer=pq.ParquetWriter(out/'registry_occurrences_raw.parquet',raw.schema,compression='zstd')
                raw_writer.write_table(raw); raw_total += raw.num_rows

                enriched=enrich_quality(raw,policy)
                mask=pc.invert(enriched.column('hard_false_positive'))
                research=enriched.filter(mask)
                hard_fp_rows=enriched.num_rows-research.num_rows
                hard_fp_total += hard_fp_rows; research_total += research.num_rows
                if research.num_rows:
                    if research_writer is None:
                        research_writer=pq.ParquetWriter(out/'research_occurrences.parquet',research.schema,compression='zstd')
                    research_writer.write_table(research)
                    for corpus,alias in zip(research.column('corpus_id').to_pylist(),research.column('alias').to_pylist()):
                        research_totals[(corpus,alias)] += 1

                aliases=set(x for x in enriched.column('alias').to_pylist() if x is not None)
                for alias in aliases:
                    sub=enriched.filter(pc.equal(enriched.column('alias'),pa.scalar(alias)))
                    if sub.num_rows==0: continue
                    if alias not in alias_writers:
                        alias_writers[alias]=pq.ParquetWriter(by_alias/safe_alias_filename(alias),sub.schema,compression='zstd')
                    alias_writers[alias].write_table(sub)
                    meta=alias_meta[alias]; meta['raw_rows'] += sub.num_rows
                    sub_fp=sum(bool(x) for x in sub.column('hard_false_positive').to_pylist())
                    meta['hard_fp_rows'] += sub_fp; meta['research_rows'] += sub.num_rows-sub_fp
                    meta['canonical'].update(x for x in sub.column('canonical_entity').to_pylist() if x)
                    meta['entity_type'].update(x for x in sub.column('entity_type').to_pylist() if x)
    finally:
        if raw_writer is not None: raw_writer.close()
        if research_writer is not None: research_writer.close()
        for aw in alias_writers.values(): aw.close()
    if raw_writer is None: raise RuntimeError('no occurrence files')

    with (out/'research_term_totals.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(['corpus_id','alias','research_count'])
        for (corpus,alias),count in sorted(research_totals.items()): w.writerow([corpus,alias,count])

    with (out/'by_alias_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['alias','file','precision_class','raw_rows','research_rows','hard_false_positive_rows','canonical_entities','entity_types'])
        for alias in sorted(alias_meta):
            meta=alias_meta[alias]; p=policy.get(alias,{})
            w.writerow([alias,f'by_alias/{safe_alias_filename(alias)}',p.get('precision_class','UNCLASSIFIED'),meta['raw_rows'],meta['research_rows'],meta['hard_fp_rows'],'|'.join(sorted(meta['canonical'])),'|'.join(sorted(meta['entity_type']))])

    if sum(m['raw_rows'] for m in alias_meta.values()) != raw_total:
        raise RuntimeError('per-alias raw row total does not equal merged occurrence total')
    if research_total + hard_fp_total != raw_total:
        raise RuntimeError('research + hard-false-positive totals do not reconcile to raw total')

    manifest={
        'schema_version':'GCI-REGISTRY-MERGE-1.2',
        'batch_count':len(manifests),'shard_count':len(summaries),'expected_shards':args.expected_shards,
        # Backward-compatible acceptance field used by the already-running workflow.
        'occurrence_count':raw_total,
        'raw_occurrence_count':raw_total,'research_occurrence_count':research_total,
        'hard_false_positive_count':hard_fp_total,'alias_file_count':len(alias_meta),
        'precision_policy_alias_count':len(policy),
        'corpora':sorted(set(r['corpus_id'] for r in summaries)),'raw_mutated':False,
        'locator_contract':'corpus_id + shard_ordinal + source_path + row_no + match_start/match_end',
        'quality_contract':'RAW_OCCURRENCE is never deleted; RESEARCH_OCCURRENCE excludes only deterministic hard false positives from explicit policy. LOW/MEDIUM precision hits remain and require context review.',
        'outputs':['registry_occurrences_raw.parquet','research_occurrences.parquet','by_alias/','by_alias_index.csv','shard_summary.csv','term_totals.csv','research_term_totals.csv'],
    }
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
