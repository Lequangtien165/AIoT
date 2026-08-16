# ChokePoint Full-Frame Recognition Benchmark

Offline recognition benchmark of the InsightFace (SCRFD + ArcFace) and
FAISS pipeline on the ChokePoint dataset. One gallery partition per run,
everything else as probes — every run is cross-session and, when the
gallery portal differs from the probe portal, cross-portal.

## Dataset

```text
chokepoint/
├── groundtruth/                  # XML per sequence-camera (probe source)
├── P1L/
│   └── P1L_S<d>_C<d>/<identity>/*.pgm      # 96×96 grayscale gallery crops
├── P2E/
│   └── P2E_S<d>_C<d>/<identity>/*.pgm
├── P1L_S<d>/P1L_S<d>_C<d>/*.jpg            # full-frame probe frames
└── P2E_S<d>/P2E_S<d>_C<d>.*/*.jpg          # P2E .1/.2 separate sequences
```

| Portal | Sessions | Cameras | Identities | Crops |
|--------|----------|---------|------------|-------|
| P1L | 4 (S1–S4) | 3 (C1–C3) | 25 (0001, 0003–0007, 0009–0027) | 16,698 |
| P2E | 4 (S1–S4) | 3 (C1–C3) | 29 (25 shared + 0002, 0028–0030) | 16,272 |
| **Total** | | | | **32,970** |

Probes: **92,334** XML-listed full-frame JPGs (37,416 person, 54,918 empty).
P2E `.1`/`.2` are separate recording sequences and must not be merged.
P2E S5 has no ground truth or crops and is excluded.

The four P2E-only identities act as natural unknown/not-enrolled probes in
P1L-gallery runs.

## Method

### Partitioning and runs

A partition is all crops of one `(portal, session)`. Eight runs:

| Run | Gallery | Probes |
|-----|---------|--------|
| run-p1l-s1 | P1L-S1 (C1–C3) | all 7 other partitions |
| run-p1l-s2 | P1L-S2 | … |
| run-p1l-s3 | P1L-S3 | … |
| run-p1l-s4 | P1L-S4 | … |
| run-p2e-s1 | P2E-S1 | … |
| run-p2e-s2 | P2E-S2 | … |
| run-p2e-s3 | P2E-S3 | … |
| run-p2e-s4 | P2E-S4 | … |

Each prediction is scoped: `same_portal_cross_session` (same portal,
different session) or `cross_portal` (different portal).

### Gallery embedding

Each 96×96 PGM crop is embedded with `FaceEngine.embed_aligned_image`
(SCRFD detection + ArcFace 512-d, `fill=0.9` template alignment,
L2-normalized). Embeddings are cached in `embeddings.npy` +
`embedding_manifest.json`; each run builds its FAISS `IndexFlatIP` from
the partition's cached vectors.

### Full-frame probe pipeline

Each probe frame is read by OpenCV, passed through SCRFD
(`FaceEngine.detect_faces`), matched to XML ground truth, embedded with
`embed_detected_face`, and searched in the FAISS gallery. A GT person
matches a detection when the midpoint of the two XML eye coordinates lies
inside its bbox; ties resolve by nearest bbox center then highest
confidence. Unmatched GT persons are missed; unassigned detections are
spurious.

Threshold is fixed at `0.45` for all eight runs.

### Probe inference cache

Raw SCRFD detections and ArcFace embeddings are a **fixed,
partition-independent transform** (`JPG → detections → embeddings`). None
of it depends on the gallery partition, FAISS index, or threshold.
Precomputing this transform once and reusing it across the 8 folds is
equivalent to pre-extracting pretrained-model features before
cross-validation — no data leakage.

**Phase 1 — build and freeze** (`--probe-cache build`): one inference pass
over all 92,334 unique frames. Each frame is detected once, each detection
is embedded once. Results are written to `benchmark-output/probe_cache/`
(manifest + embeddings + fingerprint) and frozen under a `probe_cache_id`.

**Phase 2 — read-only evaluation** (`--probe-cache read`): each of the 8
runs reads only frames outside its gallery partition. **100% cache hit
required** — any miss/stale entry fails with an error instead of falling
back to live inference. Matching, FAISS search, thresholding, and outcomes
are recomputed per run.

The cache is keyed by a fingerprint of: model SHA-256 hashes, `det_size`,
`det_thresh`, `template_fill`, effective providers, and library versions.
Any mismatch raises `ProbeCacheStale`.

**Never cached:** GT-to-detection matching, FAISS scores, predicted
identities, threshold outcomes, run summaries.

### Why the cache was necessary

- Serial full-frame inference on M1 (CoreML EP): ~66–70 ms/frame →
  646,338 logical combos ≈ 12–15 h.
- 8 parallel CoreML workers fail: ANE is shared, 13 min stuck at init.
- `det_size=320` crashes CoreML (static output shapes baked at 640).
- The cache reduces this to one pass over 92,334 frames (~2 h build) plus
  8 read-only runs (minutes), reuse factor 7.0.

## Outcomes per probe person

- `correct` — identity in gallery, score >= threshold, predicted == true.
- `false_reject` — identity in gallery but read failure, detection miss,
  embedding failure, or top score < threshold.
- `misidentified` — identity in gallery, score >= threshold, wrong
  predicted identity.
- `not_enrolled` — identity absent from the gallery partition. Excluded
  from closed-set metrics; with score >= threshold also a `false_accept`.

## Metrics

Recognition (unchanged):

- accuracy, false_reject_rate, misidentification_rate per run
- same-portal vs cross-portal accuracy split per run
- not_enrolled count, false_accept_rate (open-set)
- micro and macro across runs, plus same-portal and cross-portal splits
- FAISS search latency p50/p95

Detection (additive):

- matched/missed faces, total/spurious detections, GT face frames
- detection recall and precision, empty-frame false-positive rate
- detection latency p50/p95 and probe embedding latency p50/p95
- empty frames never affect recognition counts; `ACC + FRR + MisID = 1`

Cache (additive):

- `probe_cache_mode`, `probe_cache_id`, `probe_cache_build_seconds`
- `probe_cache_hits/misses/stale`, `probe_cache_hit_rate`
- `unique_probe_frames`, `logical_probe_frames`, `cache_reuse_factor`
- `cache_lookup_p50_ms/p95_ms`
- `predictions.csv` additive fields: `inference_source`, `cache_entry_id`,
  `probe_cache_id`

## Outputs

```text
benchmark-output/
├── embeddings.npy                     # N × 512 float32 gallery cache
├── embedding_manifest.json/.csv
├── predictions.csv                    # one row per probe person, all runs
├── run_summary.csv                    # one row per run
├── session_camera_summary.csv         # per probe partition/camera + scope
├── overall_summary.csv                # micro/macro + scope splits
├── probe_cache/                       # frozen probe inference cache
│   ├── probe_cache_manifest.json
│   ├── probe_cache_embeddings.npy
│   └── probe_cache_fingerprint.json
├── CONTEXT.md                         # dataset + method + results
└── SUMMARY.md                         # tables generated from CSVs
```

Only `CONTEXT.md`, `SUMMARY.md`, `overall_summary.csv`, `run_summary.csv`,
and `session_camera_summary.csv` are committed; everything else is
gitignored.

## Commands

```bash
# phase 1: build probe inference cache (~2 h on M1 CoreML)
python scripts/benchmark_chokepoint.py --probe-cache build

# phase 2: 8 read-only runs (minutes; build mode continues automatically)
python scripts/benchmark_chokepoint.py --probe-cache read

# precheck a small deterministic sample
python scripts/benchmark_chokepoint.py --precheck 10

# cap probe frames per run (galleries stay complete)
python scripts/benchmark_chokepoint.py --limit 300

# force gallery re-embed
python scripts/benchmark_chokepoint.py --no-cache
```

## Implementation checklist

### Batch 1 — Ground-truth parsing and detection matching

- [x] #1 Typed ChokePoint XML parsing and exact JPG path resolution
- [x] #2 Deterministic ground-truth-to-SCRFD detection matching
- [x] #3 Parser, sequence-mapping, midpoint-matching, and malformed-input tests

### Batch 2 — End-to-end benchmark pipeline

- [x] #4 Separate PGM gallery discovery from full-frame probe discovery
- [x] #5 Replace crop probe evaluation with the full-frame pipeline (live or cached)
- [x] #6 Preserve recognition metric definitions under detection failure
- [x] #7 Keep output schemas compatible and add auditable detection fields
- [x] #8 Keep recognition and detection denominators separate

### Batch 3 — CLI behavior and automated verification

- [x] #9 Adapt precheck and limit modes to full-frame probes
- [x] #10 Evaluator regression tests for all recognition and detection outcomes
- [x] #11 Verify syntax, unit tests, and real-data precheck

### Batch 4 — Full run and reproducible result artifacts

- [x] #12 Run the complete 8-run benchmark and validate global invariants
- [x] #13 Regenerate `SUMMARY.md` from end-to-end outputs
- [x] #14 Update benchmark documentation for the full-frame cached method
- [x] #15 Allow only compact benchmark results to be committed

## Global definition of done

- Batch 2 starts only after Batch 1 parser and matching tests pass.
- The full benchmark starts only after all unit tests and real-data
  precheck pass.
- Existing metric names and formulas remain available with documented
  meanings.
- Probe detections and embeddings come from the frozen probe inference
  cache built once with `--probe-cache build`; the 8 runs read it at a
  required 100% hit rate; matching, FAISS search, thresholding, and
  outcomes are recomputed per run and are never cached.
- Generated results are checked against raw CSV counts before
  documentation is updated.

## Out of scope

- P2E S5 (no ground-truth XML or PGM gallery crops).
- RTSP replay, tracking, MQTT, audit logging, and MediaMTX integration.
- Threshold sweep or calibration; threshold remains fixed at `0.45`.
- Replacing PGM enrollment galleries with detections from full-frame JPGs.
- Committing ChokePoint data, biometric crops, embeddings, individual
  predictions, or detection-event logs.
