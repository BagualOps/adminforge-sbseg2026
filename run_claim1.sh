#!/usr/bin/env bash
# Claim #1: apply time scales linearly with fleet size.
# Builds a local Docker fleet (debian:bookworm-slim, sshd), runs the cold
# apply + no-op apply on N=1 and N=5 hosts.
# ~6 min first run (+2 min image build), ~4 min subsequent.
set -euo pipefail; cd "$(dirname "$0")"
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
export ADMINFORGE_STATE="$WORK/state"; mkdir -p "$ADMINFORGE_STATE"
SSH_KEY="$WORK/adminforge_id"
ssh-keygen -q -t ed25519 -N "" -f "$SSH_KEY"

NET="afclaim1-$$"; IMG="adminforge-perf:latest"
docker network create "$NET" >/dev/null

build_image() {
    if docker image inspect "$IMG" >/dev/null 2>&1; then return 0; fi
    echo "Building fleet image..."
    docker build -q -t "$IMG" -f- infra/testlab <<'DOCKERFILE' >/dev/null
FROM debian:bookworm-slim@sha256:sha256:63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e
RUN apt-get update -qq && apt-get install -y -qq openssh-server sudo >/dev/null && rm -rf /var/lib/apt/lists/*
RUN useradd -m -s /bin/bash adminforge && mkdir -p /home/adminforge/.ssh && chmod 700 /home/adminforge/.ssh
ARG ADMINFORGE_PUBKEY
RUN echo "$ADMINFORGE_PUBKEY" > /home/adminforge/.ssh/authorized_keys && chmod 600 /home/adminforge/.ssh/authorized_keys && chown -R adminforge:adminforge /home/adminforge/.ssh && echo 'adminforge ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/adminforge
RUN mkdir -p /run/sshd
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-o", "UseDNS=no"]
DOCKERFILE
}

build_image

run_n() {
    local N=$1
    local CONTAINERS=""
    # Spin up N containers
    for i in $(seq 1 "$N"); do
        local cname="afc-${N}-${i}"
        docker run -d --rm --name "$cname" --network "$NET" \
            --tmpfs /tmp:exec --tmpfs /run -e ADMINFORGE_PUBKEY="$(cat "${SSH_KEY}.pub")" "$IMG" >/dev/null
        CONTAINERS="$CONTAINERS $cname"
    done
    sleep 2  # let sshd settle
    # Build fleet file from container IPs
    for cname in $CONTAINERS; do
        local ip=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$cname")
        echo "$cname ansible_host=$ip ansible_user=adminforge ansible_ssh_private_key_file=$SSH_KEY"
    done > "$WORK/inventory.ini"
    # Generate state in AdminForge
    > "$WORK/fleet.txt"
    for cname in $CONTAINERS; do
        local ip=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$cname")
        echo "$ip $cname" >> "$WORK/fleet.txt"
        python3 -m adminforge.cli.main server add --hostname "$cname" --ip "$ip" --auto 2>/dev/null
    done
    # Time cold apply
    local t0; t0=$(date +%s.%N)
    python3 -m adminforge.cli.main apply --yes 2>/dev/null
    local t1; t1=$(date +%s.%N)
    local cold=$(python3 -c "print($t1-$t0)")
    # Time no-op apply
    t0=$(date +%s.%N)
    python3 -m adminforge.cli.main apply --yes 2>/dev/null
    t1=$(date +%s.%N)
    local noop=$(python3 -c "print($t1-$t0)")
    # Cleanup
    for cname in $CONTAINERS; do docker stop "$cname" >/dev/null 2>&1; done
    python3 -c "print(${cold},${noop},${cold}/${N})"
}

echo "Claim #1: measuring N=1 and N=5..."
r1=$(run_n 1); r5=$(run_n 5)
cold1=$(echo "$r1" | cut -d, -f1); noop1=$(echo "$r1" | cut -d, -f2); ph1=$(echo "$r1" | cut -d, -f3)
cold5=$(echo "$r5" | cut -d, -f1); noop5=$(echo "$r5" | cut -d, -f2); ph5=$(echo "$r5" | cut -d, -f3)

ok=true
python3 -c "exit(0 if abs(($ph5-$ph1)/max($ph1,$ph5)*100)<40 else 1)" || ok=false
python3 -c "exit(0 if float($noop5)<2 else 1)" || ok=false
verdict="OK"; $ok || verdict="FAIL"

cat <<EOF
══════════════════════════════════════════════════════════════
  Claim #1 — Apply time scales linearly with fleet size
══════════════════════════════════════════════════════════════
  N=1  cold apply : $(python3 -c "print(f'{float($cold1):.1f}')") s   no-op apply : $(python3 -c "print(f'{float($noop1):.2f}')") s
  N=5  cold apply : $(python3 -c "print(f'{float($cold5):.1f}')") s   no-op apply : $(python3 -c "print(f'{float($noop5):.2f}')") s
  Per-host cold   : $(python3 -c "print(f'{float($ph5):.1f}')") s/host  (N=5)
  No-op constant  : N=1 $(python3 -c "print(f'{float($noop1):.2f}')")s N=5 $(python3 -c "print(f'{float($noop5):.2f}')")s
  Assertion: per-host at N=1 and N=5 differ by < 40%, no-op < 2 s  →  ${verdict}
══════════════════════════════════════════════════════════════
EOF
$ok
