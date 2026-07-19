# Research Artefacts

> **Installation, minimal test, and the three claims are documented in the [artifact README](../README.md); the full tool documentation is in [docs/TOOL.md](../docs/TOOL.md).**

All artefacts of the AdminForge paper are publicly available at the links below.

## Tool

- [Artifact README (CTA)](../README.md) and [full tool documentation](../docs/TOOL.md)
- [Conceptual model specification](../docs/modelagem-v1.pdf) (entities, central rule, use cases)

## Usability study (replication package)

- [Materials overview and status of each artefact](../docs/usability-study/README.md)
- [Participant task script](../docs/usability-study/ROTEIRO_PARTICIPANTE.md) (Tasks 0-9, Alice scenario)
- [Questionnaire instruments](../docs/usability-study/QUESTIONARIO.md) (profile, immediate post-task ratings, TAM-based post-test)
- [Facilitator guide](../docs/usability-study/GUIA_FACILITADOR.md) (session setup, seeded drift, observation sheet, interview script)
- [Google Forms generators](../docs/usability-study/) (`criar-formulario-google.gs`, `criar-formulario-consentimento.gs`)
- [Docker laboratory](../docs/usability-study/lab/) (three sshd containers, bootstrap and reset scripts)

## Performance experiments

- Harness and configuration: [infra/perf/](../infra/perf/); raw per-repetition results and aggregates land under `infra/perf/results/` with the camera-ready claims (`run_claim1.sh` to `run_claim3.sh` at the repository root)
