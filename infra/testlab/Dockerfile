FROM debian:bookworm-slim

ARG ADMINFORGE_PUBKEY=""

RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-server \
        sudo \
        ca-certificates \
        passwd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

RUN useradd -m -s /bin/bash adminforge \
    && echo 'adminforge ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/adminforge \
    && chmod 0440 /etc/sudoers.d/adminforge \
    && mkdir -p /home/adminforge/.ssh \
    && chmod 700 /home/adminforge/.ssh \
    && echo "$ADMINFORGE_PUBKEY" > /home/adminforge/.ssh/authorized_keys \
    && chmod 600 /home/adminforge/.ssh/authorized_keys \
    && chown -R adminforge:adminforge /home/adminforge/.ssh

RUN ssh-keygen -A \
    && sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config \
    && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D", "-e"]
