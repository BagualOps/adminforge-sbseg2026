# Performance harness

Reproducible performance and scalability experiments for AdminForge. The
numbers reported in the paper's Performance Evaluation section are computed
from `results/results.json`, which is produced by the scripts in this
directory. Everything uses only the Python standard library, Docker and the
OpenSSH client; the Ansible baseline runs from a Docker control-node
container built by the harness, so no Ansible is installed on the host.

## Testbed

- Fleet: N Debian bookworm-slim containers running only sshd, built from
  `infra/testlab/Dockerfile` (operator public key baked in, `adminforge`
  user with NOPASSWD sudo). Containers are reached directly through their
  bridge-network IPs on port 22, so no host port mapping is involved.
- Declared state per run: 10 admins with throwaway ed25519 keys, 2 admin
  groups (5 members each), all servers in one server group, one permission
  granting shell to the first group and one granting restricted sudo
  (profile with 2 allowed commands) to the second group.
- Fresh containers for every repetition of the cold-apply cells; the same
  fleet is reused for the no-op, incremental and revocation cells within a
  repetition. Containers are removed between fleet sizes.

## Running

From the repository root (Docker required, no global Python packages):

```bash
python3 infra/perf/run_e1.py            # E1 scalability, N in {1,5,10,25,50}, 5 reps
python3 infra/perf/run_e2.py            # E2 Ansible comparison, N in {10,50}, 5 reps
python3 infra/perf/run_e3.py            # E3 attack-surface verification
python3 infra/perf/aggregate.py         # raw JSON -> results/results.json
python3 infra/perf/claims.py            # asserted claim lines for the paper
```

Each run writes one JSON per repetition into `results/raw/`; re-running
skips repetitions that already exist (delete the file to redo it).
Fleet sizes and repetitions are parameters, e.g.
`python3 infra/perf/run_e1.py --sizes 1,10 --reps 3`.

## Experiments

- E1 (`run_e1.py`): wall-clock of cold apply, no-op re-apply, incremental
  apply (1 admin added), revocation apply (that admin removed),
  `history verify`, `audit server --all` and `apply verify`, for each fleet
  size, 5 repetitions, median and min-max. Peak RSS of the AdminForge
  process is captured with `/usr/bin/time -v` on every cold apply.
- E2 (`run_e2.py`): the same effective operation (10 users with
  authorized_keys and sudoers on all hosts) through an equivalent
  ansible-core playbook (`ansible/playbook.yml`, builtin modules only) on
  the same containers with the same operator key. Cells: first apply and
  no-op re-run, at N=10 and N=50 with default forks, plus N=50 with
  forks=25. Fairness settings are documented in the script header and
  recorded in the raw output. Configuration effort is the total of the
  non-empty, non-comment lines of the three Ansible files, versus the
  number of AdminForge CLI commands. At N=10 the "78 YAML lines" reported
  in the paper is a **sum**: `ansible/playbook.yml` (37) + the inventory
  (15, one line per host, generated at run time in `work/` and therefore
  not committed) + `ansible/users.yml` (26) = 78. The breakdown is stored
  per repetition in the `effort` field of `results/raw/e2_n10_*.json`, and
  the AdminForge side is `setup_cli_commands` (19 + N = 29 at N=10).
- E3 (`run_e3.py`): listening TCP sockets and bound UDP sockets inside 3
  sampled managed containers (parsed from `/proc/net/tcp{,6}` and
  `/proc/net/udp{,6}`) before management and after full management plus
  several applies; plus operator-side sampling proving the AdminForge
  process tree never holds a listening socket during apply.

## Cleanup

Containers are removed automatically at the end of each run. To force it:

```bash
docker rm -f $(docker ps -aq --filter name=afperf-)
```

`work/` holds throwaway keys, state directories and the generated Ansible
inventory; it is gitignored and safe to delete.
