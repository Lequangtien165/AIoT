# AIoT Documentation Hub

Single entry point for every reader of this project. Start here instead of
hunting through individual files. All paths are relative to the repository
root; `AGENTS.md` and `BACKLOG.md` live at the root because tooling and status
tracking expect them there.

## Read This First

| Doc | What it is | Audience |
|---|---|---|
| [README.md](../README.md) | Quick start, installation, and CLI usage per module | Everyone |
| [CLI_REFERENCE.md](CLI_REFERENCE.md) | Every CLI flag of every command, generated from the argparse definitions | Engineer, operator, developer |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **Current** system architecture (2026-08): profiles, RTSP/MQTT planes, recognition, security | Teacher, developer |
| [RUNBOOK.md](RUNBOOK.md) | End-to-end operations: deploy, demo sequence, troubleshooting | Engineer, operator, demo |
| [BACKLOG.md](../BACKLOG.md) | Progress gates (Gate 1 profile deployment, Gate 2 MQTT control), demo evidence, open work | Maintainer, teacher |
| [AGENTS.md](../AGENTS.md) | Developer guide: commands, architecture invariants, test rules | Developer (also loaded by AI tooling) |

## Reading Paths

### Teacher / Grader (catch up in ~30 minutes)

1. `README.md` — what the project does and how to run it.
2. `docs/ARCHITECTURE.md` — the current design and the decisions behind it.
3. `docs/RUNBOOK.md` section 10 — the verified demo sequence (what actually ran).
4. `BACKLOG.md` — which gates are closed and which evidence is still pending.

### Developer (joining the codebase)

1. `AGENTS.md` — commands, module layout, invariants you must not break.
2. `docs/CLI_REFERENCE.md` — every flag of every command, plus cross-process invariants.
3. `docs/ARCHITECTURE.md` — component responsibilities and state machines.
4. `docs/plans/` — design contracts and reviews (see table below).
5. `BACKLOG.md` — open work and recent progress notes.

### Engineer / Operator (deploying or operating)

1. `docs/RUNBOOK.md` — role-by-role deployment and the troubleshooting table.
2. `docs/CLI_REFERENCE.md` — full flag reference when tuning a command.
3. `README.md` — platform-specific setup.

### Maintainer (yourself, after a break)

1. `docs/README.md` (this file) — re-orient.
2. `BACKLOG.md` progress notes — what changed and when.
3. `docs/plans/IMPLEMENTATION_REVIEW.md` — current gaps vs. implemented state.

## Design, Plans, And Reviews (`docs/plans/`)

These documents describe design contracts and analysis. They are **current**
unless the status column says otherwise; legacy material lives in
`docs/legacy/`.

| Doc | Status | Purpose |
|---|---|---|
| [IMPLEMENTATION_PLAN.md](plans/IMPLEMENTATION_PLAN.md) | Current (updated 2026-08-08) | What is implemented vs. remaining work per subsystem |
| [RASPBERRY_PI_TEST_PLAN.md](plans/RASPBERRY_PI_TEST_PLAN.md) | Current | Hardware test procedure for the Pi (`rpi-csi`, systemd recovery) |
| [IMPLEMENTATION_REVIEW.md](plans/IMPLEMENTATION_REVIEW.md) | Current (updated 2026-08-08) | Codebase vs. architecture review, current gaps |
| [MOTION_TRIGGERED_STREAM_STRATEGY.md](plans/MOTION_TRIGGERED_STREAM_STRATEGY.md) | Current (design done; Web Relay section is future work) | Motion-triggered session protocol and lease semantics |
| [RECOGNITION_OPTIMIZATION_PLAN.md](plans/RECOGNITION_OPTIMIZATION_PLAN.md) | Current (design done; benchmarks pending) | Split SCRFD/ArcFace realtime pipeline contract |

## Legacy Material (`docs/legacy/`)

These are the original idea-stage documents (converted from `.docx` to keep one
format). They document the **initial inspiration** — PIR hardware, dlib,
actuator, web UI — and intentionally do **not** reflect the current
architecture. Read them only for context, never as a spec.

| Doc | Original | What it contains |
|---|---|---|
| [ARCHITECTURE_REPORT_LEGACY.md](legacy/ARCHITECTURE_REPORT_LEGACY.md) | `reports/BaoCao_KienTruc_AIoT.docx` | Initial edge-cloud design and teacher-review answers (PIR/dlib/actuator, since replaced) |
| [FAISS_NOTES_LEGACY.md](legacy/FAISS_NOTES_LEGACY.md) | `reports/FAISS Document.docx` | Study notes on face encoders and FAISS (128-d `face_recognition` example; the system uses InsightFace `buffalo_l`) |

## Status Conventions

- **Current**: describes the codebase as of 2026-08-08.
- **Plan/Design**: the design is settled and implemented; remaining validation
  is tracked in `BACKLOG.md`.
- **Legacy**: idea-stage material, superseded, kept for context.

## Document Map (filesystem)

```text
README.md               quick start + documentation map
AGENTS.md               developer guide (loaded by AI tooling)
BACKLOG.md              gates, evidence, progress notes
docs/
  README.md             THIS HUB
  ARCHITECTURE.md       current architecture
  RUNBOOK.md            end-to-end operations runbook
  CLI_REFERENCE.md      every CLI flag, generated from the argparse definitions
  plans/                design contracts, test plans, reviews
  legacy/               converted idea-stage documents (not current)
reports/                removed (content moved to docs/; see git history)
```
