import csv, json, sys
from pathlib import Path
import rarfile

archive = Path(sys.argv[1])
out_csv = Path(sys.argv[2] if len(sys.argv) > 2 else 'exos_asset_dumps_index.csv')
out_json = out_csv.with_suffix('.json')

rf = rarfile.RarFile(archive)
rows = []
for info in rf.infolist():
    rows.append({
        'path': info.filename,
        'size_bytes': info.file_size,
        'compressed_bytes': info.compress_size,
        'compress_type': getattr(info, 'compress_type', None),
        'is_dir': info.isdir(),
        'is_fbx': info.filename.lower().endswith('.fbx'),
        'is_animation_path': 'animation' in info.filename.lower(),
    })

with out_csv.open('w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)
with out_json.open('w', encoding='utf-8') as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)

print('entries', len(rows))
print('fbx', sum(r['is_fbx'] for r in rows))
print('animation paths', sum(r['is_animation_path'] for r in rows))
for r in rows:
    if r['is_fbx'] or r['is_animation_path']:
        print(r['path'])
