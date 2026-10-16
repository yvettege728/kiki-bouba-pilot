# Kiki / Bouba eye-tracking pilot

A short warm-up task for getting participants used to an eye tracker (SCI 6384, Harvard GSD).

**Play in the browser:** https://yvettege728.github.io/kiki-bouba-pilot/

**Run offline:** download `kiki-bouba-pilot.html` (or Code > Download ZIP) and open it in Chrome. No install, no internet needed.

## Flow (about 3 min)

1. Follow the dot: 9 positions, 1.5 s each (accuracy check against the tracker)
2. Practice: 2 trials with feedback
3. Round 1, easy: clear kiki vs. bouba, keys `F` / `J`
4. Round 2, medium: half-spiky vs. half-round, keys `F` / `J`
5. Round 3, hard: 4 shapes, only one has a sharp point, keys `D` `F` `J` `K`
6. Results screen with CSV / JSON download

## Controls built in

- 800 ms central fixation cross before every trial
- Parametric shapes with equal area, positions counterbalanced
- Keyboard responses, cursor hidden, 10 s timeout, 500 ms blank between trials
- Sync patch in the bottom-left corner turns white while a stimulus is on screen (for aligning tracker recordings)
- Pixel AOI coordinates for every shape are logged per trial
- `Esc` stops the session and still lets you save data

## Settings

Edit the `CFG` block at the top of the script to change timings or the number of trials.

The game does not connect to the eye tracker. Record gaze in the tracker software and align it using the sync patch and timestamps.
