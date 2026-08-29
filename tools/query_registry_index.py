#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pyarrow.dataset as ds


def safe_alias_filename(alias: str) -> str:
    bad='\\/:*?"<>|\x00\n\r\t'
    name=''.join('_' if ch in bad else ch for ch in alias).strip('. ')
    return (name or 'EMPTY') + '.parquet'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--index-root',required=True)
    ap.add_argument('--alias',required=True)
    ap.add_argument('--corpus-id')
    ap.add_argument('--shard-min',type=int)
    ap.add_argument('--shard-max',type=int)
    ap.add_argument('--contains',help='optional substring required in saved context')
    ap.add_argument('--limit',type=int,default=100)
    ap.add_argument('--format',choices=['jsonl','csv'],default='jsonl')
    args=ap.parse_args()

    path=Path(args.index_root)/'by_alias'/safe_alias_filename(args.alias)
    if not path.exists():
        raise SystemExit(f'alias index not found: {path}')
    dataset=ds.dataset(path,format='parquet')
    filt=None
    def AND(x):
        nonlocal filt
        filt=x if filt is None else filt & x
    if args.corpus_id:
        AND(ds.field('corpus_id')==args.corpus_id)
    if args.shard_min is not None:
        AND(ds.field('shard_ordinal')>=args.shard_min)
    if args.shard_max is not None:
        AND(ds.field('shard_ordinal')<=args.shard_max)
    table=dataset.to_table(filter=filt)
    rows=table.to_pylist()
    if args.contains:
        rows=[r for r in rows if args.contains in (r.get('context') or '')]
    rows=rows[:args.limit]

    if args.format=='jsonl':
        for r in rows:
            print(json.dumps(r,ensure_ascii=False))
    else:
        if not rows:
            return
        w=csv.DictWriter(__import__('sys').stdout,fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

if __name__=='__main__':
    main()
