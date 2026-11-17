"""Swap kiki/bouba answers for a participant who mixed up the F/J sides.

Usage:  python analysis/fix_label_flip.py <game_log.csv or .json> [more files...]

Writes <name>_corrected.csv / .json next to each input and leaves the original untouched.
For every `response` event, `choice` is swapped (timeouts stay "timeout"), the original
answer is kept in `choice_raw`, and `correction` says what was changed. The pressed key
(`key`) is not changed. Report this post-hoc correction in the methods/limitations.
"""
import csv, json, sys
from pathlib import Path

FLIP = {'kiki': 'bouba', 'bouba': 'kiki'}
NOTE = 'label_flip: participant reversed left/right; choice swapped post-hoc, key kept as pressed'


def fix(row):
    row['choice_raw'] = row.get('choice', '')
    row['correction'] = ''
    if row.get('event') == 'response' and row.get('choice') in FLIP:
        row['choice'] = FLIP[row['choice']]
        row['correction'] = NOTE
        return 1
    return 0


for p in map(Path, sys.argv[1:]):
    out = p.with_name(p.stem + '_corrected' + p.suffix)
    if p.suffix == '.json':
        rows = json.loads(p.read_text())
        n = sum(fix(r) for r in rows)
        out.write_text(json.dumps(rows, indent=1))
    else:
        rows = list(csv.DictReader(p.open(newline='')))
        n = sum(fix(r) for r in rows)
        with out.open('w', newline='') as f:
            w = csv.DictWriter(f, list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f'{p.name}: {n} answers swapped -> {out.name}')
