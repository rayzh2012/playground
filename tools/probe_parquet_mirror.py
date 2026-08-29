#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, list_repo_files

OUT = Path('global_index_output/parquet_probe')
OUT.mkdir(parents=True, exist_ok=True)

TERMS = ['蚩尤','炎帝','赤帝','黄帝','共工','帝鸿','少昊','太昊','颛顼','九黎']
TARGETS = [
    {
        'corpus_id': 'GCI-HOLD-0001',
        'repo_id': 'Geralt-Targaryen/Literature-zh',
        'drive_basename': 'literature_zh-00233-of-00233.parquet',
        'source_suffix': 'literature_zh-00233-of-00233.parquet',
        'drive_file_id': '1rCZaQhYD0jYaFTEz4mMS_JcASLf_CraN',
        'drive_size': 80314697,
        'drive_sha256': 'd452713dfc7fecf65e713541a5c85c2f772f51e46b5cd3d6bb34b0aff3b6693e',
    },
    {
        'corpus_id': 'GCI-HOLD-0002',
        'repo_id': 'Morton-Li/ChineseWebText2.0-HighQuality',
        'drive_basename': 'data__CASIA-LM_ChineseWebText2.0_partial-001553.parquet',
        'source_suffix': 'partial-001553.parquet',
        'drive_file_id': '1QOlPzxwZHkuf8S3GqY0MS1qgrjfGx8O6',
        'drive_size': 252467982,
        'drive_sha256': '3c32c7e566b7fd103b18bbdcb9d6e5c98f1ec3d0b9f8a7c1b0d2a973a8e871ef',
    },
]

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def resolve_source_path(files: list[str], target: dict) -> str:
    exact=[x for x in files if Path(x).name == target['drive_basename']]
    if len(exact)==1:
        return exact[0]
    suffix=[x for x in files if x.endswith(target['source_suffix'])]
    if len(suffix)==1:
        return suffix[0]
    # Diagnostic fallback for renamed/flattened Drive imports.
    ordinal=target['source_suffix'].split('-')[-1].replace('.parquet','')
    fuzzy=[x for x in files if ordinal in x and x.endswith('.parquet')]
    if len(fuzzy)==1:
        return fuzzy[0]
    raise RuntimeError(
        f"Expected one HF source for {target['drive_basename']}; "
        f"suffix={target['source_suffix']}; candidates={fuzzy[:20]}"
    )

def main():
    report=[]
    occ_rows=[]
    for t in TARGETS:
        files=list_repo_files(t['repo_id'], repo_type='dataset')
        source_path=resolve_source_path(files,t)
        local=Path(hf_hub_download(repo_id=t['repo_id'], repo_type='dataset', filename=source_path))
        nbytes=local.stat().st_size
        digest=sha256(local)
        mirror_match=(nbytes == t['drive_size'] and digest == t['drive_sha256'])
        pf=pq.ParquetFile(local)
        schema=str(pf.schema_arrow)
        names=pf.schema_arrow.names
        if 'text' not in names:
            raise RuntimeError(f"text column missing: {names}")
        counts={term:0 for term in TERMS}
        contexts={term:[] for term in TERMS}
        rows_seen=0
        for batch in pf.iter_batches(columns=['text'], batch_size=2048):
            vals=batch.column(0).to_pylist()
            for text in vals:
                rows_seen += 1
                if text is None:
                    continue
                s=str(text)
                for term in TERMS:
                    c=s.count(term)
                    if c:
                        counts[term] += c
                        if len(contexts[term]) < 5:
                            pos=s.find(term)
                            context=s[max(0,pos-80):min(len(s),pos+len(term)+80)].replace('\n',' ')
                            contexts[term].append({'row_no':rows_seen,'context':context})
        if rows_seen != pf.metadata.num_rows:
            raise RuntimeError((rows_seen, pf.metadata.num_rows))
        for term in TERMS:
            for item in contexts[term]:
                occ_rows.append([
                    t['corpus_id'], t['drive_basename'], term, counts[term],
                    item['row_no'], item['context']
                ])
        report.append({
            **t,
            'hf_source_path': source_path,
            'hf_download_size': nbytes,
            'hf_sha256': digest,
            'drive_mirror_byte_identical': mirror_match,
            'parquet_rows': pf.metadata.num_rows,
            'row_groups': pf.metadata.num_row_groups,
            'top_level_columns': names,
            'schema': schema,
            'text_column': 'text',
            'pilot_term_counts': counts,
        })
        print(json.dumps({
            'corpus_id':t['corpus_id'], 'drive_file':t['drive_basename'],
            'hf_source_path':source_path, 'rows':pf.metadata.num_rows,
            'mirror_match':mirror_match, 'counts':counts
        }, ensure_ascii=False), flush=True)
        if not mirror_match:
            raise RuntimeError(f"Public source != Drive mirror for {t['drive_basename']}")

    (OUT/'parquet_mirror_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'pilot_occurrences.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['corpus_id','source_file','term','file_total_count','row_no','context'])
        w.writerows(occ_rows)

if __name__ == '__main__':
    main()
