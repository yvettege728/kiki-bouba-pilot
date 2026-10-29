"""Pool game logs and gaze metrics into one table and the four pilot figures.

Usage:
  python summarize.py <folder with kikibouba_*.csv game logs> <folder with gaze_trials_*.csv>
Writes all_trials.csv, hybrid_trials.csv and pilot_summary.png into the gaze folder.
"""
import csv, glob, json, os, sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

GAMES, GAZE = sys.argv[1], sys.argv[2]

# ---------- behaviour from every game log ----------
beh = []
for f in sorted(glob.glob(os.path.join(GAMES, 'kikibouba_*.csv'))):
    for r in csv.DictReader(open(f)):
        if r['event'] != 'response': continue
        s = json.loads(r['stim']) if r['stim'] else {}
        beh.append({'pid': r['pid'], 'trial': int(r['trial']), 'block': r['block'], 'rt_ms': float(r['rt_ms']),
                    'key': r['key'], 'correct': r['correct'], 'choice': r['choice'],
                    'm': s.get('m', ''), 'hybrid': int(s['hybrid']) if 'hybrid' in s else ''})
# ---------- gaze metrics where available ----------
gz = {}
for f in glob.glob(os.path.join(GAZE, 'gaze_trials_*.csv')):
    for r in csv.DictReader(open(f)):
        gz[(r['pid'], int(r['trial']))] = r
gaze_cols = ['gaze_samples', 'n_fix', 'first_region', 'last_region', 'switches'] + \
    [f'{k}_{R}' for R in ['target', 'other', 'prompt', 'shape', 'spiky', 'round', 'house_kiki', 'house_bouba'] for k in ['ttff', 'dwell']]
rows = []
for b in beh:
    g = gz.get((b['pid'], b['trial']))
    has = bool(g) and int(g['gaze_samples']) > 0.5 * b['rt_ms'] / 5   # at least half the expected 200 Hz samples
    row = dict(b, has_gaze=int(has))
    for c in gaze_cols: row[c] = g[c] if has else ''
    rows.append(row)
with open(os.path.join(GAZE, 'all_trials.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)

num = lambda v: float(v) if v not in ('', None) else 0.0
G = [r for r in rows if r['has_gaze']]
gaze_pids = sorted({r['pid'] for r in G}, key=int)
all_pids = sorted({r['pid'] for r in rows}, key=int)

fig, ax = plt.subplots(2, 2, figsize=(12, 9))
fig.suptitle(f'Kiki/bouba pilot: behaviour n = {len(all_pids)}, gaze n = {len(gaze_pids)} (P{", P".join(gaze_pids)})', fontsize=13)

# 1. habituation: RT and fixations over the first trials
a = ax[0, 0]
for p in all_pids:
    pr = sorted([r for r in rows if r['pid'] == p and r['block'] in ('practice', 'easy')], key=lambda r: r['trial'])
    a.plot(range(1, len(pr) + 1), [r['rt_ms'] / 1000 for r in pr], color='0.75', lw=1)
med = [np.median([r['rt_ms'] / 1000 for r in rows if r['block'] in ('practice', 'easy') and
       sorted([q['trial'] for q in rows if q['pid'] == r['pid'] and q['block'] in ('practice', 'easy')]).index(r['trial']) == i])
       for i in range(8)]
a.plot(range(1, 9), med, color='#534AB7', lw=2.5, label='median RT (all)')
a2 = a.twinx()
fx = [np.mean([num(r['n_fix']) for r in G if r['block'] in ('practice', 'easy') and
      sorted([q['trial'] for q in rows if q['pid'] == r['pid'] and q['block'] in ('practice', 'easy')]).index(r['trial']) == i] or [np.nan])
      for i in range(8)]
a2.plot(range(1, 9), fx, color='#D85A30', lw=2, ls='--', marker='o', label='mean fixations (gaze)')
a.axvspan(0.5, 2.5, color='#E1F5EE', zorder=0); a.text(1.5, a.get_ylim()[1] * 0.92, 'practice', ha='center', fontsize=9, color='#0F6E56')
a.set_xlabel('Trial (practice + round 1)'); a.set_ylabel('RT (s)'); a2.set_ylabel('Fixations per trial', color='#D85A30')
a.set_title('1. Getting used to the task'); a.legend(loc='upper right', fontsize=8); a2.legend(loc='center right', fontsize=8)

# 2. rounds 1 vs 2: where gaze goes
a = ax[0, 1]
stats = {}
for blk, name in [('easy', 'Round 1\nclear'), ('medium', 'Round 2\nvaried')]:
    R = [r for r in G if r['block'] == blk]
    share = [num(r['dwell_target']) / (num(r['dwell_target']) + num(r['dwell_other'])) for r in R if num(r['dwell_target']) + num(r['dwell_other']) > 0]
    first_t = [r['first_region'] == 'target' for r in R if r['first_region'] in ('target', 'other')]
    looked_other = [num(r['dwell_other']) > 0 for r in R]
    stats[name] = (100 * np.mean(share), 100 * np.mean(first_t), 100 * np.mean(looked_other), len(R))
labels = ['Target dwell share', 'First look on target', 'Trials that checked\nthe other shape']
x = np.arange(3); wbar = 0.36
for k, (name, v) in enumerate(stats.items()):
    bars = a.bar(x + (k - 0.5) * wbar, v[:3], wbar, label=f'{name.replace(chr(10), " ")} (n={v[3]})', color=['#AFA9EC', '#534AB7'][k])
    for bb, val in zip(bars, v[:3]): a.text(bb.get_x() + bb.get_width() / 2, val + 1.5, f'{val:.0f}%', ha='center', fontsize=9)
a.axhline(50, color='0.6', ls=':', lw=1); a.set_xticks(x, labels, fontsize=9); a.set_ylim(0, 110); a.set_ylabel('%')
a.set_title('2. Rounds 1 and 2: varied shapes make people compare'); a.legend(fontsize=8)

# 3. round 3 psychometric curve (behaviour, all participants)
a = ax[1, 0]
S = [r for r in rows if r['block'] == 'sort' and r['key'] != 'timeout']
levels = sorted({r['m'] for r in S if not r['hybrid']})
pk = [100 * np.mean([r['choice'] == 'kiki' for r in S if not r['hybrid'] and r['m'] == m]) for m in levels]
nk = [sum(1 for r in S if not r['hybrid'] and r['m'] == m) for m in levels]
a.plot(levels, pk, marker='o', color='#534AB7', lw=2.5, label='single shapes')
for m, v, n in zip(levels, pk, nk): a.text(m, v + 4, f'{v:.0f}%', ha='center', fontsize=8)
hy = [r for r in S if r['hybrid']]
hk = 100 * np.mean([r['choice'] == 'kiki' for r in hy])
a.scatter([0.5], [hk], marker='D', s=80, color='#D85A30', zorder=5, label=f'hybrids, half spiky (n={len(hy)})')
a.text(0.53, hk - 7, f'{hk:.0f}%', color='#D85A30', fontsize=9)
a.axhline(50, color='0.6', ls=':', lw=1); a.set_ylim(-5, 110)
a.set_xlabel('Spikiness m (0 = round, 1 = spiky)'); a.set_ylabel('% sent to KIKI house')
a.set_title(f'3. Round 3: categorisation curve (n = {len(all_pids)}, timeouts excluded)'); a.legend(fontsize=8, loc='upper left')

# 4. hybrids: which half was looked at last, and what they answered
a = ax[1, 1]
HG = [r for r in G if r['block'] == 'sort' and r['hybrid'] == 1 and r['key'] != 'timeout']
groups = {}
for r in HG:
    lr = r['last_region'] if r['last_region'] in ('spiky', 'round') else 'other / none'
    groups.setdefault(lr, []).append(r['choice'])
order = [g for g in ['spiky', 'round', 'other / none'] if g in groups]
for i, g in enumerate(order):
    k = sum(c == 'kiki' for c in groups[g]); bo = len(groups[g]) - k
    a.bar(i, k, color='#534AB7', label='answered KIKI' if i == 0 else None)
    a.bar(i, bo, bottom=k, color='#F0997B', label='answered BOUBA' if i == 0 else None)
    a.text(i, k + bo + 0.1, f'{k}/{k + bo} KIKI', ha='center', fontsize=9)
a.set_xticks(range(len(order)), [f'last look:\n{g} half' if g != 'other / none' else 'last look:\nhouse / none' for g in order])
a.set_ylim(0, max(len(v) for v in groups.values()) + 1.2); a.set_ylabel('Hybrid trials'); a.set_title(f'4. Hybrids: last half looked at vs answer (gaze n = {len(gaze_pids)})')
sd = [num(r['dwell_spiky']) for r in HG]; rd = [num(r['dwell_round']) for r in HG]
a.text(0.98, 0.97, f'mean dwell before answer\nspiky half {np.mean(sd):.0f} ms\nround half {np.mean(rd):.0f} ms',
       transform=a.transAxes, ha='right', va='top', fontsize=9, bbox=dict(fc='white', ec='0.8'))
a.legend(fontsize=8, loc='center right')

plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(os.path.join(GAZE, 'pilot_summary.png'), dpi=150)

with open(os.path.join(GAZE, 'hybrid_trials.csv'), 'w', newline='') as f:
    cols = ['pid', 'trial', 'rt_ms', 'choice', 'first_region', 'last_region', 'switches', 'dwell_spiky', 'dwell_round', 'ttff_spiky', 'ttff_round']
    w = csv.DictWriter(f, cols, extrasaction='ignore'); w.writeheader(); w.writerows(HG)

print('rounds 1-2:', {k.replace(chr(10), ' '): [round(x) for x in v] for k, v in stats.items()})
print('psychometric:', dict(zip(levels, [round(v) for v in pk])), 'hybrid kiki %', round(hk), 'n', len(hy))
print('hybrid gaze groups:', {g: (sum(c == 'kiki' for c in v), len(v)) for g, v in groups.items()}, 'spiky/round dwell', round(np.mean(sd)), round(np.mean(rd)))
print('habituation median RT:', [round(m, 2) for m in med], 'fix:', [round(v, 1) for v in fx])
