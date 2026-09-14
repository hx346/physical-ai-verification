# RoboVerify — Physical AI Verification Platform

> **AI proposes designs. RoboVerify proves them.**

[![Status](https://img.shields.io/badge/status-P0%20Product%20Validation-orange)]()
[![License](https://img.shields.io/badge/license-TBD-lightgrey)]()

**中文文档：[README.zh-CN.md](./README.zh-CN.md)**

RoboVerify is an **engineering verification runtime** for robot and physical-AI systems.
It is *not* a simulator, not a digital-twin platform, and not an AI design assistant.

It does not answer *"how should I design this robot cell?"* — it answers:

- **Does this design actually meet the requirements?** Why, or why not?
- Which parameters are the real bottleneck (sensitivity-ranked, not LLM-scored)?
- Which sensors or actuators are actually unnecessary?
- Which configuration is the cheapest one that still passes (Pareto frontier)?
- How far will simulation diverge from reality (Sim2Real gap)?
- What **evidence** justifies moving the design to the next stage?

Every conclusion is traceable:

```
Requirement → Constraint → Test Case → Simulation → Experiment → Real Test → Evidence → Decision
```

## Core Principles

1. **LLM is replaceable.** Any provider (GPT / Gemini / Claude / Qwen / DeepSeek / local) is only a *Reasoning Provider*. The system must remain fully functional with no LLM attached.
2. **AI proposes hypotheses, the system proves them.** Verdicts (PASS/FAIL) come from formulas, solvers, Monte Carlo, simulation and real tests — never from prompts.
3. **Recommendations are future-free.** Task decomposition, part recommendation and test-plan generation are treated as commodity capabilities, not the moat.
4. **Reality > Verification > Experiment > Simulation > Optimization > Knowledge > AI reasoning.** Investment priority follows this order.
5. **Every verdict is traceable** to requirement, configuration, method, version and evidence.

## Key Concepts

| Concept | Role |
|---|---|
| **Engineering IR** | Language-neutral intermediate representations: Task / Requirement / System / State / Environment / Experiment / Evidence IR (JSON Schema, versioned in [`schemas/`](./schemas/)) |
| **Asset Registry** | Engineering asset models (robots, sensors, grippers) with error parameters carrying an explicit **provenance** level: `datasheet` / `literature` / `measured` / `calibrated` |
| **Verification Kernel** | Constraint solver, uncertainty engine (RSS + Monte Carlo → P50/P90/P95 + CI), end-to-end latency budgeting, observability analysis, reachability/collision |
| **Experiment Engine** | LHS / Monte Carlo sampling over the experiment space (illumination, occlusion, depth noise, …) + sensitivity analysis (SALib) |
| **Simulation SPI** | Simulator-agnostic adapter interface; gz-sim first, Isaac Sim planned |
| **Evidence Graph** | Every requirement verdict is backed by linked simulation/experiment/real-test evidence records |
| **Verification Matrix** | The hero UI page: requirement × metric × current × required × verdict × evidence |

Example — the page the whole product hangs on:

| Requirement | Metric | Current | Required | Result | Evidence |
|---|---|---:|---:|---|---|
| R01 | Position accuracy (P95) | 4.8 mm | < 3 mm | **FAIL** | E102 |
| R02 | Reach | 1.1 m | > 1.0 m | PASS | E103 |
| R03 | Cycle time (P95) | 5.4 s | < 6 s | PASS | E104 |
| R04 | Picking success rate | 94 % | > 98 % | **FAIL** | E105 |

## Architecture

```
              ┌──────────────────┐
              │      Web UI      │  Vue 3 — Verification Matrix is the hero page
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐   Java 25 · Spring Boot 4 (modular monolith)
              │     Platform     │   projects · requirements · assets · evidence
              │   (API + IR +    │   reports · audit · job orchestration
              │    persistence)  │
              └───┬──────────┬───┘
   REST/OpenAPI   │          │  jobs (PostgreSQL SKIP LOCKED)
                   ▼          ▼
        ┌──────────────┐  ┌─────────────────────┐
        │    Runtime   │  │       Workers       │  Python 3.12
        │ (sync kernel)│  │ sim · experiment ·  │
        │              │  │ calibration         │
        └──────┬───────┘  └──────────┬──────────┘
               │                     ▼
               │           ┌───────────────────┐
               │           │ gz-sim · ROS 2    │  Linux Docker (Simulation Adapter SPI)
               │           │ (later: Isaac Sim)│
               │           └─────────┬─────────┘
               ▼                     ▼
        ┌────────────────────────────────────┐
        │  PostgreSQL (JSONB)  ·  Seafile    │  IRs · evidence · URDF/CAD · logs · reports
        └────────────────────────────────────┘
```

Full design: [`docs/architecture.md`](./docs/architecture.md) · Decisions: [`docs/adr/`](./docs/adr/)

## Tech Stack

| Layer | Choice |
|---|---|
| Platform API | Java 25 (LTS) · Spring Boot 4.x · Flyway · Sa-Token · JdbcTemplate in M0 (MyBatis-Plus returns once it ships a Boot 4 starter) |
| Engineering runtime | Python 3.12+ · FastAPI · NumPy / SciPy / Pandas · Pydantic v2 |
| Kinematics & collision | Pinocchio · python-fcl / trimesh |
| Sensitivity & DOE | SALib · (later: pymoo · Optuna) |
| Simulation | gz-sim + ROS 2 in Linux Docker behind an adapter SPI (Isaac Sim at V0.5) |
| Data | PostgreSQL 17+ (relational + JSONB) · Seafile via WebDAV behind an ObjectStore SPI (URDF / CAD / datasets / logs / reports) |
| Queue | PostgreSQL `FOR UPDATE SKIP LOCKED` (Temporal only when scale demands it) |
| Frontend | Vue 3 · TypeScript · Vite · Ant Design Vue · ECharts |
| LLM | Provider-agnostic adapter, optional — core flows work without any LLM |
| Deploy | Docker Compose (Linux); Windows development uses WSL2 for simulation |
| CI | GitHub Actions |

## Repository Layout

```
.
├── README.md / README.zh-CN.md   bilingual project docs
├── docs/
│   ├── architecture.md           system design, contracts, boundaries
│   ├── development-plan.md       milestones M0–M4, DoD, risks, gates
│   └── adr/                      architecture decision records
├── schemas/                      Engineering IR JSON Schemas (single source of truth)
├── backend/                      Java platform service (Spring Boot 4 modular monolith)
├── runtime/                      Python engineering runtime (kernel + workers)
├── frontend/                     Vue 3 web UI
└── deploy/                       docker-compose, env templates, deployment docs
```

## Quick Start (Docker, full stack)

Everything runs in containers — nothing is deployed on the host except Docker:

```bash
git clone git@github.com:hx346/physical-ai-verification.git
cd physical-ai-verification/deploy
docker compose up -d postgres backend runtime frontend   # build images on first run

# Web UI       -> http://localhost:18000   (admin / roboverify123)
# Backend API  -> http://localhost:18090/actuator/health
# Runtime      -> http://localhost:18081/health
# PostgreSQL   -> localhost:15432          (roboverify / roboverify)
docker compose up -d            # optional: also start the Seafile object-store stack
# Seafile Web  -> http://localhost:18080  (admin@roboverify.local / roboverify123)
```

After changing code: `docker compose build backend runtime frontend && docker compose up -d`.

## Roadmap

| Version | Theme | Content |
|---|---|---|
| **V0.1** (M0–M4, due 2027-01) | Design Verification | analytic kernel → gz-sim adapter → experiment engine → read-only ROS 2 ingestion · scenario: **vision-guided bin picking** |
| V0.3 | Simulation Verification | richer sim evidence, multi-metric coverage |
| V0.5 | Experiment Platform | Isaac Sim, synthetic data, DOE |
| V0.8 | Real Robot Integration | telemetry, Real2Sim gap reports |
| V1.0 | Real2Sim | calibrated sensor/robot models — first commercial product |
| V2.0 | Design Optimization | Pareto frontier over configuration space |
| V3.0 | Agentic Engineering | AI generates designs, RoboVerify proves them, loop |

Milestone detail with acceptance criteria: [`docs/development-plan.md`](./docs/development-plan.md)

## Status

**V0.1 code complete (2026-09-14)**: analytic verification kernel (constraint / uncertainty / timing /
observability / success model), verification orchestration with evidence chain (input fingerprint,
kernel version, assumptions, traceId), experiment engine (LHS/MC + Sobol sensitivity, async worker),
Markdown reports with experiment section, and the read-only real-test path (CSV telemetry,
Sim2Real gap, calibration versioning) are all working. The gz-sim adapter and ROS 2 collector are
**code-complete, integration pending** (see [CHANGELOG](./CHANGELOG.md) Pending items).
End-to-end demo: `bash deploy/demo/run-demo.sh`.

Still **P0 — Product Validation**: Gate 1 (≥70% recall on historical projects) decides whether
productization continues.

## License

TBD.
