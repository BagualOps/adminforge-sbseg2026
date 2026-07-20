# AdminForge: Declarative Privileged-Identity Management for Linux Server Fleets

This repository is the artifact of the paper *"AdminForge: Declarative Privileged-Identity Management for Linux Server Fleets"* (SBSeg 2026, Salão de Ferramentas, Código Aberto). AdminForge is an open-source command-line tool that manages users, SSH keys, and access permissions on Linux server fleets: the operator declares the desired access state, previews the resulting changes, and applies them over SSH, with every operation appended to a local, hash-chained operation history and no resident service installed on managed hosts. The paper reports an exploratory usability evaluation (five experienced Linux administrators completed the full nine-task workflow without prior training, median ratings 6/7) and a performance evaluation on a local Docker fleet.

<p align="center"><img src="docs/img/architecture.png" alt="AdminForge architecture: the operator drives the CLI; Planner and Deployer carry changes to the managed hosts over SSH; the Auditor records and inspects; the Store keeps the declared state and history in local JSON files" width="72%"></p>
<p align="center"><img src="docs/img/use-cases.png" alt="Use cases: the superadmin registers admins, SSH keys and servers, manages groups, grants or revokes access, previews and applies changes, audits users and services, and views the history" width="46%"></p>

# Estrutura do readme.md

1. [Considered Seals](#considered-seals)
2. [Basic information](#basic-information)
3. [Dependencies](#dependencies)
4. [Security concerns](#security-concerns)
5. [Installation](#installation)
6. [Minimal test](#minimal-test)
7. [Experiments](#experiments) (Claims #1–#3)
8. [LICENSE](#license)

Repository layout: `adminforge/` (the tool: one package per architecture module: `cli/`, `store/`, `planner/`, `deployer/`, `auditor/`, plus `domain.py`); `tests/` (offline unit tests); `infra/perf/` (performance-experiment harness and results); `docs/` (full tool documentation in `docs/TOOL.md`, usage guides, conceptual model, and the usability-study replication package under `docs/usability-study/`); `paper_data/AVAILABILITY.md` (index of every paper artefact).

# Considered Seals

The considered seals are: **Available (SeloD), Functional (SeloF), Sustainable (SeloS), and Reproducible (SeloR)**.

# Basic information

| Component | Requirement |
|---|---|
| OS | Linux x86-64 |
| Runtime | Python ≥ 3.11 (standard library only; no third-party packages at run time) |
| System packages | `git`, `docker` (Engine ≥ 24, for the experiment fleet), `ssh`, `ssh-keygen` |
| Hardware | any 4-core / 8 GB RAM machine; ~2 GB free disk |

Paper experiments ran on: AMD Ryzen 5 8600G (6 cores), 32 GB RAM, Linux kernel 6.17, Python 3.12, Docker Engine 29.4.

### Reproduction time (and why it depends on your hardware)

The claim scripts **measure live on your machine**, so wall-clock times scale with CPU speed, disk, and (first run only) how long Docker takes to build the fleet images and pull base images. The table below is a full clean-clone run on the reference machine above (a fast desktop). **On a slower CPU, a laptop, or a cold Docker cache, expect noticeably longer, especially for Claim #1.** What is *not* hardware-dependent, and is what each claim actually asserts, is the printed **`→ OK`** verdict and the ratios/counts behind it (per-host flatness, the ~200× no-op speedup over Ansible, the SLOC and import counts, the recomputed study statistics).

| Step | Command | Reference machine (Ryzen 5 8600G) |
|---|---|---|
| Install | `pip install -e ".[dev]"` | ~5 s |
| Minimal test | `pytest` + the `af` commands | ~3 s |
| **Claim #1** | `./run_claim1.sh` | **~3.5 min** (Docker build + a live N=1/5 ladder and an N=10 Ansible run) |
| **Claim #2** | `./run_claim2.sh` | **~1 s** |
| **Claim #3** | `./run_claim3.sh` | **~0.1 s** |

> Times are the reference machine's; your numbers will differ. Only Claim #1 uses Docker; the first run also builds the fleet and Ansible-controller images (add build time on a cold cache). If you reproduce on other hardware, please open a PR/issue adding a row here.

# Dependencies

The tool has **zero third-party Python dependencies at run time** (`dependencies = []` in `pyproject.toml`; only the standard library is imported). Optional extras: `completion` (argcomplete, shell autocompletion) and `dev` (pytest ≥ 8.0, for the test suite). Host tools needed are only **git, docker, python3, ssh, and ssh-keygen** (all standard on a Linux dev box). The experiment fleet uses the `debian:12-slim` Docker image with `openssh-server` and `sudo` (built locally by the claim scripts). **Ansible is never installed on the host:** Claim #1 builds an Ansible control-node container (`python:3.12-slim` + `ansible-core` + `openssh-client`) and runs the playbook from it, on the fleet's Docker network. Claim #1's first run therefore needs **internet** to pull the base images and install `ansible-core` into the controller image (Claims #2 and #3 are fully offline).

# Security concerns

Everything runs locally: no telemetry, no external API calls, no credentials leave the machine. The claim scripts create a local Docker fleet whose SSH ports bind to `127.0.0.1` only (never exposed to the network); containers, networks, and temporary state directories are removed at the end of each script. The tool itself only ever distributes SSH *public* keys to the containers it manages.

# Installation

```bash
git clone https://github.com/BagualOps/adminforge-sbseg2026
cd adminforge-sbseg2026
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # < 1 min; installs the tool + pytest only
```

After this, the `af` command (alias of `adminforge`) is available.

# Minimal test

Offline unit tests, then one real registration observed end to end with the hash chain verified (~30 s, no Docker needed):

```bash
python3 -m pytest tests/ -q     # expected: "112 passed, 1 skipped" (~3 s, no network)
export ADMINFORGE_STATE=$(mktemp -d)
ssh-keygen -q -t ed25519 -N "" -f /tmp/alice_key
af user add --username alice --name "Alice Souza" --email alice@example.com --key-file /tmp/alice_key.pub
af history verify
```

Expected final lines:

```
  OK  user add alice  (OP-0001)
  OK  user key add alice  (OP-0002)
  OK  chain intact (last hash: <64 hex digits>)
```

# Experiments

The paper makes three claims. Each is one command and prints a result box ending in `→ OK` so the evaluator knows it came out right.  Claim #1 needs Docker (the rest do not).  Wall-clock times scale with CPU speed; the assertions are hardware-independent (ratios, counts, recomputed statistics).

## Claim #1: Linear per-host cost, and an instant "is anything pending?" against Ansible

**What the paper asserts.** Cold `apply` costs a roughly constant time per host (so it scales linearly with the fleet), and a no-change `apply` is answered from local state without touching any host, far faster than an Ansible re-run that must reconnect to every host. The script measures both **live on your machine**, into a throwaway directory (it never reuses the committed reference numbers):

- **(a) Scalability:** a reduced ladder (N=1 and N=5, 1 repetition) via `infra/perf/run_e1.py`; checks the per-host cold-apply cost is flat (< 40% difference) and the no-op stays under 2 s.
- **(b) Comparison with Ansible:** N=10 via `infra/perf/run_e2.py`; the Ansible control node runs as a container (no Ansible on the host), applies the equivalent playbook to the same fleet, and the script checks AdminForge's no-change apply is at least 5x faster than Ansible's equivalent re-run.

**Execution:** one command (needs Docker + internet on first run).

```bash
./run_claim1.sh
```

**Expected result** (numbers are from the reference machine; **your absolute seconds will differ** - what the claim asserts is the final `-> OK` and the hardware-independent quantities: per-host flatness, the tens-to-hundreds-x no-op speedup over Ansible, and 78 lines of YAML vs 29 commands):

```
======================================================================
  Claim #1: linear per-host cost, and instant "is anything pending?"
======================================================================
  (a) Scalability (base image, measured live)
      N=1  cold apply :   13.0 s     no-op apply : 0.05 s
      N=5  cold apply :   64.9 s     no-op apply : 0.07 s
      Per-host cold   : N=1 13.0 s/host   N=5 13.0 s/host   (diff 0.0%)

  (b) Comparison with Ansible at N=10 (python3 image, measured live)
      First apply     : AdminForge   14.1 s (parallel)   Ansible   23.6 s
      No-op re-run    : AdminForge   0.09 s (local)      Ansible  20.81 s   (240x faster)
      Write effort    : AdminForge 29 commands    Ansible 78 lines of YAML

  Assertions (hardware-independent):
    per-host cold flat (<40% diff)                         -> OK
    no-op apply < 2 s                                      -> OK
    AdminForge no-op >= 5x faster than Ansible re-run      -> OK
  Overall  ->  OK
======================================================================
```

The full 5-repetition ladder up to N=50, all Ansible configurations, and the attack-surface check live in `infra/perf/`, with the paper's committed per-repetition results under `infra/perf/results/`.

## Claim #2: Usability-study statistics recomputed from the anonymized response data

**What the paper asserts.**  All 39 numbers reported in the paper's per-task table and construct-aggregate table (medians, means, IQRs, standard deviations, top-box percentages).  The evaluator recomputes them from the raw data without repeating the study; the annotation was performed by the paper authors and is not expected to be reproduced.

**Execution:** one command (~2 s, no Docker).

```bash
./run_claim2.sh
```

**Expected result:**

```
═══════════════════════════════════════════════════════════════════════════════════
  Claim #2: Usability-study statistics recomputed from the
  anonymized response data  (5 participants, no re-run of the study)
═══════════════════════════════════════════════════════════════════════════════════
  Task                               Confidence               Ease
  ──────────────────────────  ─────────────────  ─────────────────
  Register user and SSH key   7 (6.6)           6 (6.0)
  ... (all 9 tasks) ...
  Construct                         Med       IQR   Top%    Mean     SD
  Perceived usefulness (PU)           6   3.8–7.0     60%   5.40   1.76
  Perceived ease of use (PEOU)        6   4.5–7.0     70%   5.55   1.61
  Intention to use (ITU)              6   4.5–7.0     73%   5.47   1.77
  Security and confidence (SC)        6   3.0–7.0     65%   5.30   1.81

  All 39 study numbers match the paper  →  OK
═══════════════════════════════════════════════════════════════════════════════════
```

**Reference data in the repository:** anonymized spreadsheet `paper_data/study-responses.xlsx` (timestamps removed, no names, no emails) and the questionnaire instrument `paper_data/study-questionnaire.pdf`.

## Claim #3: Executed code surface under 4,000 lines with zero third-party runtime imports

**What the paper asserts.** The tool's own source is under 4,000 lines of code (blank lines and comments excluded) and the base install imports nothing beyond the Python standard library at run time.

**Execution:** one command (< 5 s, no Docker, no network).

```bash
./run_claim3.sh
```

**Expected result (deterministic; the numbers below are exact, not hardware-dependent):**

```
══════════════════════════════════════════════════════════════
  Reivindicação #3: attack surface of the base install
══════════════════════════════════════════════════════════════
  Own code (adminforge/**.py)   : 3916 lines of code (claim: < 4,000)
  Third-party runtime imports   : 0   (claim: 0)

  Expected: code < 4,000 and 0 third-party imports  →  OK
══════════════════════════════════════════════════════════════
```

The line count excludes blank lines and comments (`grep -vhE '^[[:space:]]*(#|$)'`); the import check loads every runtime module and asserts none resolves to `site-packages`. The full measurement harness behind the paper's performance section (5-repetition ladders up to N=50 hosts, the Ansible comparison, and the attack-surface audit) lives in `infra/perf/`. Claim #2's reference data is in `paper_data/`.

# LICENSE

[GNU AGPL-3.0](LICENSE).
