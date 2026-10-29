"""Align a Pupil Labs Neon recording with a kiki/bouba game log.

Neon gaze is in scene-camera pixels, and the screen moves in that view as the
head moves. This script:
  1. finds the laptop screen in every scene-video frame (the game background
     shows up as a saturated lavender quad) and fits its four corners,
  2. undistorts corners and gaze with the scene-camera intrinsics,
  3. maps gaze and Neon fixations to game screen pixels with a per-frame homography,
  4. syncs clocks (wall-clock UTC first, then refined on the follow-the-dot phase),
  5. writes per-trial metrics with the same regions as align.html.

Usage:
  python neon_align.py <neon_export_folder> <game_log.csv> <out_folder>
"""
import csv, json, sys, math, os, bisect, datetime as dt
import numpy as np
import cv2

REC, GAME, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)

# ---------- game log ----------
recs = list(csv.DictReader(open(GAME)))
for r in recs:
    r['t_ms'] = float(r['t_ms'])
    r['stim'] = json.loads(r['stim']) if r['stim'] else None
start = next(r for r in recs if r['event'] == 'session_start')
W, H = start['stim']['W'], start['stim']['H']
pid = recs[0]['pid']
def wall_ms(r):
    return dt.datetime.fromisoformat(r['wall'].replace('Z', '+00:00')).timestamp() * 1000
# game time 0 in UTC ms (median over records, Date has 1 ms resolution)
game0_utc = float(np.median([wall_ms(r) - r['t_ms'] for r in recs]))

# ---------- scene camera ----------
cam = json.load(open(os.path.join(REC, 'scene_camera.json')))
K = np.array(cam['camera_matrix']); D = np.array(cam['distortion_coefficients']).ravel()
def undist(pts):
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    return cv2.undistortPoints(pts, K, D, P=K).reshape(-1, 2)

# ---------- screen detection per frame ----------
video = next(f for f in os.listdir(REC) if f.endswith('.mp4'))
frame_ts = [int(r['timestamp [ns]']) for r in csv.DictReader(open(os.path.join(REC, 'world_timestamps.csv')))]

def line_intersect(l1, l2):
    (vx1, vy1, x1, y1), (vx2, vy2, x2, y2) = l1, l2
    A = np.array([[vx1, -vx2], [vy1, -vy2]]); b = np.array([x2 - x1, y2 - y1])
    s = np.linalg.solve(A, b)[0]
    return [x1 + s * vx1, y1 + s * vy1]

def find_screen(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (100, 70, 110), (128, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs: return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.02 * img.shape[0] * img.shape[1]: return None
    raw = c.reshape(-1, 2)
    # the screen must not be cut off by the frame edge, or its corners are unknown
    h_img, w_img = img.shape[:2]
    if ((raw[:, 0] <= 2) | (raw[:, 0] >= w_img - 3) | (raw[:, 1] <= 2) | (raw[:, 1] >= h_img - 3)).mean() > 0.01: return None
    # undistort the outline first so the screen edges become straight lines
    pts = undist(raw[::2])
    hull = cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2).astype(float)
    s, d = hull.sum(1), hull[:, 0] - hull[:, 1]
    quad = np.array([hull[s.argmin()], hull[d.argmax()], hull[s.argmax()], hull[d.argmin()]])  # tl tr br bl
    # refine: fit a line to the middle of each side, intersect neighbours
    # (robust to the small black sync patch cutting the bottom-left corner)
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        ab = b - a; L = np.linalg.norm(ab)
        if L < 10: return None
        t = ((pts - a) @ ab) / L**2
        dist = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
        sel = pts[(t > 0.15) & (t < 0.85) & (dist < max(12, 0.03 * L))]
        if len(sel) < 10: return None
        lines.append(cv2.fitLine(sel.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel())
    return np.array([line_intersect(lines[(i - 1) % 4], lines[i]) for i in range(4)])

cap = cv2.VideoCapture(os.path.join(REC, video))
corners = []
i = 0
while True:
    ok, img = cap.read()
    if not ok: break
    q = find_screen(img)
    corners.append(q)   # already in undistorted pixels
    i += 1
cap.release()
n_found = sum(q is not None for q in corners)
print(f'frames: {len(corners)}, screen found in {n_found} ({100 * n_found / len(corners):.0f}%)')
frame_ts = frame_ts[:len(corners)]

dst = np.array([[0, 0], [W, 0], [W, H], [0, H]], np.float64)
Hs = [None if q is None else cv2.getPerspectiveTransform(q.astype(np.float32), dst.astype(np.float32)) for q in corners]

def to_screen(ts_ns, x, y):
    j = bisect.bisect_right(frame_ts, ts_ns) - 1
    if j < 0 or j >= len(Hs) or Hs[j] is None: return None
    p = undist([[x, y]])
    v = Hs[j] @ np.array([p[0, 0], p[0, 1], 1.0])
    return v[0] / v[2], v[1] / v[2]

# ---------- gaze + fixations to screen ----------
gaze = []
for r in csv.DictReader(open(os.path.join(REC, 'gaze.csv'))):
    if r['worn'] != '1' or r['blink id']: continue
    ts = int(r['timestamp [ns]'])
    p = to_screen(ts, float(r['gaze x [px]']), float(r['gaze y [px]']))
    if p: gaze.append((ts / 1e6, p[0], p[1]))   # utc ms
fix = []
for r in csv.DictReader(open(os.path.join(REC, 'fixations.csv'))):
    t0, t1 = int(r['start timestamp [ns]']), int(r['end timestamp [ns]'])
    p = to_screen((t0 + t1) // 2, float(r['fixation x [px]']), float(r['fixation y [px]']))
    if p: fix.append((t0 / 1e6, t1 / 1e6, p[0], p[1]))
print(f'gaze samples on screen: {len(gaze)}, fixations: {len(fix)}')

# ---------- clock sync on the dot phase ----------
dots = []
for r in recs:
    if r['event'] == 'dot_on':
        off = next(o for o in recs if o['event'] == 'dot_off' and o['trial'] == r['trial'])
        dots.append((r['t_ms'] + 200, off['t_ms'] + 200, r['stim']['x'], r['stim']['y']))
G_t = np.array([g[0] for g in gaze]); G_xy = np.array([[g[1], g[2]] for g in gaze])
def cost(o):   # o = extra offset (ms) on top of wall-clock sync
    tot = 0
    for g0, g1, x, y in dots:
        a, b = np.searchsorted(G_t, [game0_utc + g0 + o, game0_utc + g1 + o])
        if b - a < 5: tot += 400; continue
        tot += np.minimum(400, np.hypot(*(G_xy[a:b] - [x, y]).T)).mean()
    return tot / len(dots)
grid = np.arange(-3000, 3001, 5)
cs = np.array([cost(o) for o in grid])
flat = grid[cs <= cs.min() + 1]
extra = float((flat[0] + flat[-1]) / 2)
print(f'wall-clock sync refined by {extra:+.0f} ms; dot-phase mean error {cs.min():.0f} px')
def g_time(utc):   # utc ms -> game ms
    return utc - game0_utc - extra

# constant offset correction: median gaze bias over the dots (e.g. glasses sitting slightly off)
bias = []
for g0, g1, x, y in dots:
    a, b = np.searchsorted(G_t, [game0_utc + g0 + extra, game0_utc + g1 + extra])
    if b - a >= 5: bias.append(np.median(G_xy[a:b] - [x, y], axis=0))
bias = np.median(bias, axis=0) if len(bias) >= 4 else np.zeros(2)
G_xy = G_xy - bias
gaze = [(t, x - bias[0], y - bias[1]) for t, x, y in gaze]
fix = [(a, b, x - bias[0], y - bias[1]) for a, b, x, y in fix]
print(f'offset correction: x {-bias[0]:+.0f} px, y {-bias[1]:+.0f} px')

# per-dot accuracy and bias (after correction)
dot_rows = []
for k, (g0, g1, x, y) in enumerate(dots):
    a, b = np.searchsorted(G_t, [game0_utc + g0 + extra, game0_utc + g1 + extra])
    e = G_xy[a:b] - [x, y]
    dot_rows.append({'dot': k, 'x': x, 'y': y, 'n': int(b - a),
                     'median_err_px': round(float(np.median(np.hypot(*e.T))), 1) if b > a else '',
                     'bias_x': round(float(e[:, 0].mean()), 1) if b > a else '', 'bias_y': round(float(e[:, 1].mean()), 1) if b > a else ''})

# ---------- regions (same as align.html) ----------
def in_box(x, y, b, m):
    return b and b[0] - m <= x <= b[0] + b[2] + m and b[1] - m <= y <= b[1] + b[3] + m
def region_fn(block, stim, m=30):
    if block == 'sort':
        kl = stim['kiki_side'] == 'left'
        def f(x, y):
            if in_box(x, y, stim['house_left'], 0): return 'house_kiki' if kl else 'house_bouba'
            if in_box(x, y, stim['house_right'], 0): return 'house_bouba' if kl else 'house_kiki'
            if not in_box(x, y, stim['bbox'], m): return 'none'
            if stim.get('hybrid') and stim.get('sector_center') is not None:
                a = math.atan2(y - stim['cy'], x - stim['cx']) - stim['sector_center']
                a = math.atan2(math.sin(a), math.cos(a))
                return 'spiky' if abs(a) <= stim['sector_half'] else 'round'
            return 'shape'
        return f
    def f(x, y):
        for s in stim:
            if in_box(x, y, s['aoi'], m): return 'target' if s['target'] else 'other'
        if y < H * 0.2: return 'prompt'
        return 'none'
    return f
REGIONS = ['target', 'other', 'prompt', 'shape', 'spiky', 'round', 'house_kiki', 'house_bouba']

# ---------- per-trial metrics ----------
trials = []
for on in [r for r in recs if r['event'] == 'stim_on']:
    resp = next((r for r in recs if r['event'] == 'response' and r['trial'] == on['trial']), None)
    if not resp or not resp['rt_ms']: continue
    g0 = on['t_ms']; g1 = g0 + float(resp['rt_ms'])
    reg = region_fn(on['block'], on['stim'])
    F = [(max(g_time(a), g0), min(g_time(b), g1), x, y) for a, b, x, y in fix if g_time(b) > g0 and g_time(a) < g1]
    F = [(a, b, x, y, reg(x, y)) for a, b, x, y in F]
    a_idx, b_idx = np.searchsorted(G_t, [g0 + game0_utc + extra, g1 + game0_utc + extra])
    row = {'pid': pid, 'trial': int(on['trial']), 'block': on['block'], 'rt_ms': float(resp['rt_ms']),
           'correct': resp['correct'], 'choice': resp['choice'],
           'm': on['stim']['m'] if on['block'] == 'sort' else '',
           'hybrid': int(on['stim']['hybrid']) if on['block'] == 'sort' else '',
           'gaze_samples': int(b_idx - a_idx), 'n_fix': len(F)}
    real = [f for f in F if f[4] != 'none']
    row['first_region'] = real[0][4] if real else ''
    row['last_region'] = real[-1][4] if real else ''
    row['switches'] = sum(1 for p, q in zip(real, real[1:]) if p[4] != q[4])
    for R in REGIONS:
        fr = [f for f in F if f[4] == R]
        row['ttff_' + R] = round(fr[0][0] - g0) if fr else ''
        row['dwell_' + R] = round(sum(b - a for a, b, *_ in fr)) if fr else ''
    trials.append(row)

cols = list(trials[0].keys())
with open(os.path.join(OUT, f'gaze_trials_{pid}.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(trials)
with open(os.path.join(OUT, f'gaze_dots_{pid}.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, list(dot_rows[0].keys())); w.writeheader(); w.writerows(dot_rows)
with open(os.path.join(OUT, f'gaze_samples_{pid}.csv'), 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['t_game_ms', 'x', 'y'])
    for t, x, y in gaze: w.writerow([round(g_time(t), 1), round(x, 1), round(y, 1)])
json.dump({'pid': pid, 'frames': len(corners), 'screen_found': n_found, 'sync_extra_ms': extra,
           'dot_error_px': round(float(cs.min()), 1), 'offset_correction_px': [round(-float(bias[0]), 1), round(-float(bias[1]), 1)]}, open(os.path.join(OUT, f'sync_{pid}.json'), 'w'), indent=2)
print('wrote', OUT)
