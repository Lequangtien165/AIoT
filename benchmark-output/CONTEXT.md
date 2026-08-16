# ChokePoint Benchmark — Context

## Dataset

**ChokePoint** is a real-world face recognition dataset published by NICTA
(now Data61, CSIRO). It simulates a surveillance chokepoint — people walk
through doorways under overhead cameras with uncontrolled lighting, pose,
and expression.

> Y. Wong, S. Chen, S. Mau, C. Sanderson, B.C. Lovell.
> "Patch-based Probabilistic Image Quality Assessment for Face Selection
> and Improved Video-based Face Recognition."
> *IEEE CVPR Biometrics Workshop*, 2011.

The dataset was downloaded from the NICTA/Data61 distribution page.
It is not redistributed in this repository.

## Structure

```text
chokepoint/
├── P1L/                              # portal 1, leave direction
│   ├── P1L_S1_C1/<identity>/*.pgm    # session 1, camera 1 (gallery crops)
│   ├── P1L_S1_C2/…
│   ├── P1L_S1_C3/…
│   ├── P1L_S2_C1/… … P1L_S4_C3/…
├── P2E/                              # portal 2, enter direction
│   ├── P2E_S1_C1/<identity>/*.pgm
│   ├── … P2E_S4_C3/…
├── P1L_S1/ … P2E_S4/                 # full-frame JPGs (probe frames)
└── groundtruth/                      # XML annotations (probe ground truth)
```

Each `.pgm` file is a **96×96 grayscale face crop** pre-extracted by the
dataset authors using their face detector. Identity directories (`0001`,
`0003`, …) are consistent across portals — the same number is the same
person. The full-frame JPG directories and the per-sequence XML files under
`groundtruth/` define the probe frames.

### Counts

| Portal | Sessions | Cameras | Identities | Crops |
|--------|----------|---------|------------|-------|
| P1L    | 4 (S1–S4) | 3 (C1–C3) | 25 (0001, 0003–0007, 0009–0027) | 16,698 |
| P2E    | 4 (S1–S4) | 3 (C1–C3) | 29 (25 shared + 0002, 0028–0030) | 16,272 |
| **Total** | | | | **32,970** |

Probe frames (XML-listed full-frame JPGs): **92,334** total, of which
**37,416** are person frames and **54,918** are empty frames. P2E `.1` and
`.2` are separate recording sequences per camera and must not be merged
despite overlapping frame numbers. P2E S5 exists as full frames only (no
pre-extracted crops and no ground truth) and is excluded from this benchmark.

### Why two portals matter

P1L and P2E are physically different locations with different lighting,
background, and camera angles. A model that works well on P1L may degrade
on P2E. Cross-portal evaluation measures this generalization gap.

The four P2E-only identities (0002, 0028, 0029, 0030) naturally act as
**unknown/not-enrolled** probes in P1L-gallery runs, enabling open-set
false-accept measurement without artificial construction.

## Method

### Partitioning

A **partition** is all crops of one `(portal, session)` across its three
cameras. There are 8 partitions (P1L × 4 sessions + P2E × 4 sessions).

### Evaluation protocol

One run per partition:

1. **Gallery** — all crops of the partition, embedded as a FAISS
   `IndexFlatIP` index (cosine similarity on L2-normalized vectors).
2. **Probes** — every XML-listed full-frame JPG in every *other* partition
   of the entire dataset. Detection and embedding are a fixed,
   partition-independent transform, so raw SCRFD detections and ArcFace
   embeddings are built **once** into a frozen probe cache
   (`benchmark-output/probe_cache/`, `--probe-cache build`) and the 8 runs
   read it read-only (`--probe-cache read`) with a required 100% hit rate.
   Matching, FAISS search, thresholding, and outcomes are never cached and
   are recomputed per run.
3. Each person frame is matched to its SCRFD detections: a GT person matches
   a detection when the midpoint of the two XML eye coordinates lies inside
   its bbox; ties resolve by nearest bbox center then highest confidence.
   The matched face is embedded and searched against the gallery (top-1
   nearest neighbor). Empty frames never enter recognition counts — they
   only feed the detection metrics.
4. If `score ≥ threshold` and the predicted identity matches the true
   identity → **correct**. Otherwise → **false_reject** (below threshold,
   or the person was not read/detected/embedded) or **misidentified**
   (above threshold, wrong identity).
5. Probes whose true identity does not exist in the gallery are
   **not_enrolled** and excluded from closed-set accuracy. If such a probe
   scores above threshold, it is also a **false_accept**.

Each prediction is tagged with a **scope**:

- `same_portal_cross_session` — probe is from the same portal as the gallery
  but a different session.
- `cross_portal` — probe is from the other portal entirely.

This yields 8 runs. Every run is cross-session by construction. Four of
them (P1L gallery, P2E probes and vice versa) are also cross-portal.

### Why this protocol

- **Leave-one-session-out** is standard for ChokePoint because sessions
  capture the same people on different days/walks, so gallery and probe
  never share the same recording.
- **Cross-portal** tests whether the model generalizes across different
  physical environments — the hardest realistic scenario.
- **Full-frame probes** exercise the live pipeline end to end: the same
  SCRFD detection, eye-midpoint matching, embedding, and search steps used
  in production, including empty frames that can trigger spurious
  detections.
- **Not-enrolled probes** arise naturally from the identity mismatch
  between portals, testing open-set rejection without artificial
  construction.
- **Fixed threshold** (0.45) avoids overfitting to the dataset — it is
  the same threshold used in the live recognition pipeline.

### Pipeline

1. **Gallery embedding**: each 96×96 PGM crop is embedded using
   `FaceEngine.embed_aligned_image` (SCRFD detection + ArcFace 512-d
   embedding, `fill=0.9` template alignment). Embeddings are L2-normalized.
2. **Gallery caching**: all 32,970 embeddings are computed once and stored
   in `embeddings.npy` + `embedding_manifest.json`. Subsequent runs reuse
   the cache.
3. **Probe evaluation**: each XML-listed frame's cached raw inference is
   looked up (detections + embeddings + build-time latencies), matched to
   ground truth by eye midpoint, and searched in the FAISS gallery index.
   A cache miss raises instead of falling back to live inference.
4. **Detection metrics**: matched/missed faces, total/spurious detections,
   detection recall/precision, empty-frame false-positive rate, and
   detection/embedding latency are reported alongside the unchanged
   recognition metrics.

## Results

### Overall (threshold = 0.45, full-frame probes, probe cache read-only)

| Metric | Value |
|--------|-------|
| Gallery crops | 32,970 |
| Embedded OK | 32,970 (0 skipped) |
| Person probes (all 8 runs) | 261,912 |
| Closed-set queries | 251,516 |
| Not-enrolled queries | 10,396 |
| **Micro accuracy** | **0.9886** |
| Macro accuracy | 0.9884 |
| Same-portal accuracy (micro) | 0.9982 |
| Cross-portal accuracy (micro) | 0.9809 |
| False accepts | 0 |
| Detection recall | 0.9998 |
| Detection precision | 0.6012 |
| Empty-frame false positive rate | 0.3711 |
| Probe cache | 646,338 hits / 0 misses, hit rate 1.0, reuse factor 7.0, build 6,941 s |

### Per-run

| Run | Gallery | Vectors | Probe frames | Person probes | Acc | FRR | MisID | Same | Cross | Not-enr | FAR |
|-----|---------|---------|--------------|---------------|-----|-----|-------|------|-------|---------|-----|
| P1L S1 | P1L | 3,564 | 81,660 | 33,513 | 0.9838 | 0.0162 | 0.0 | 0.9999 | 0.9697 | 2,599 | 0.0 |
| P1L S2 | P1L | 4,289 | 81,045 | 32,705 | 0.9867 | 0.0133 | 0.0 | 0.9996 | 0.9760 | 2,599 | 0.0 |
| P1L S3 | P1L | 4,596 | 80,250 | 32,392 | 0.9814 | 0.0186 | 0.0 | 0.9994 | 0.9668 | 2,599 | 0.0 |
| P1L S4 | P1L | 4,249 | 80,850 | 32,683 | 0.9806 | 0.0194 | 0.0 | 0.9998 | 0.9647 | 2,599 | 0.0 |
| P2E S1 | P2E | 3,339 | 83,556 | 33,739 | 0.9935 | 0.0065 | 0.0 | 0.9951 | 0.9921 | 0 | — |
| P2E S2 | P2E | 4,429 | 83,592 | 32,608 | 0.9931 | 0.0069 | 0.0 | 0.9963 | 0.9906 | 0 | — |
| P2E S3 | P2E | 3,974 | 77,307 | 32,372 | 0.9950 | 0.0050 | 0.0 | 0.9968 | 0.9936 | 0 | — |
| P2E S4 | P2E | 4,530 | 78,078 | 31,900 | 0.9933 | 0.0067 | 0.0 | 0.9990 | 0.9890 | 0 | — |

### Key observations

- **Full-frame pipeline outperforms the crop benchmark** (micro 0.9764 →
  0.9886): SCRFD on full frames with eye-midpoint matching is strictly
  better than the dataset's pre-extracted crops.
- **Same-portal accuracy (99.8%)** is near-perfect — the model handles
  session-to-session variation with minimal error.
- **Cross-portal accuracy (98.1%)** drops only ~1.7 points, roughly half the
  crop-era gap (3.2 points) — full-frame detection generalizes better
  across the two physical environments.
- **MisID = 0 in every run** — no probe was matched above threshold to the
  wrong gallery identity; the residual error is entirely false rejects.
- **Zero false accepts** — no unknown person was matched to a gallery
  identity at threshold 0.45.
- **P2E gallery runs outperform P1L** (0.993–0.995 vs 0.981–0.987): P2E has
  more gallery identities (29 vs 25) and better frontal pose from the
  "enter" direction.
- **Detection recall 0.9998** — only 42 of 261,912 GT faces were missed;
  the 4 `Premature end of JPEG file` warnings in the build log show as
  `read_error` cache entries and are handled by the same rules as live
  read failures.
- **Empty-frame FPR 0.3711** — 37% of GT-empty frames carry at least one
  spurious detection; this reflects the dataset's labeling (walk-throughs,
  bystanders) and is the main driver of the low detection precision 0.6012.
- **Probe cache integrity**: 646,338 logical frame/run combinations served
  from 92,334 unique frames at 100% hit rate with zero misses — the cache
  is deterministic, and each run's own partition was excluded from its
  probes regardless of cache contents.

## Output files

| File | Rows | Description |
|------|------|-------------|
| `overall_summary.csv` | 1 | Micro/macro accuracy, scope splits, detection + probe cache aggregates |
| `run_summary.csv` | 8 | Per-run recognition + detection metrics, latencies, cache stats |
| `session_camera_summary.csv` | 168 | Per probe partition + camera breakdown |
| `predictions.csv` | 261,912 | Every individual prediction (additive columns: `inference_source`, `cache_entry_id`, `probe_cache_id`) |
| `embedding_manifest.json` | 32,970 | Per-crop embedding status, latency, metadata |
| `embeddings.npy` | 32,970 × 512 | Cached gallery embedding vectors (float32) |
| `probe_cache/` | 92,334 | Frozen probe inference cache (`probe_cache_manifest.json`, `probe_cache_embeddings.npy`, `probe_cache_fingerprint.json`) |

The CSV/NPY/probe-cache files are **not committed** to git — they are large
and contain derived data. Only `CONTEXT.md`, `SUMMARY.md`,
`overall_summary.csv`, `run_summary.csv`, and `session_camera_summary.csv`
are committed; the plan document
(`docs/plans/CHOKEPOINT_BENCHMARK.md`) captures the
methodology for reproducibility.

## Reproducing

```bash
# phase 1: one inference pass over all 92,334 unique frames (raw SCRFD
# detections + ArcFace embeddings frozen under a fingerprint)
python scripts/benchmark_chokepoint.py --probe-cache build

# phase 2: 8 read-only runs (matching + FAISS + threshold recomputed; 100%
# cache hit rate required, misses fail instead of falling back to live)
python scripts/benchmark_chokepoint.py --probe-cache read

# build mode continues into the 8 runs automatically after the cache is built

# precheck a deterministic sample of person/empty frames per portal
python scripts/benchmark_chokepoint.py --precheck 10

# cap probe frames per run (galleries stay complete)
python scripts/benchmark_chokepoint.py --limit 300

# force gallery re-embed (ignore cache)
python scripts/benchmark_chokepoint.py --no-cache
```

Requires the ChokePoint dataset extracted under `chokepoint/` and
recognition dependencies installed (see `requirements-recognition-macos.txt`
or `requirements-recognition-windows.txt`).
