# Lab do estudo de usabilidade — operação

Ambiente padronizado pra rodar o [estudo moderado](../METODOLOGIA-OPCOES.md) do AdminForge.
O participante entra via `ssh` numa máquina onde a gente hospeda isto, dá `source` no `env.sh`
e usa o `adminforge` (com autocomplete). Os três alvos da "frota" — `web-01`, `web-02`, `db-03` —
são containers Docker; o `adminforge` em si roda no host, num venv criado pelo `prep.sh`.

## Requisitos da máquina-host

- Docker + `docker compose` (v2).
- `python3` (≥ 3.11) com `venv`.
- Acesso SSH pra o participante entrar (conta dedicada recomendada — ver abaixo).
- Portas `2201`, `2202`, `2203` livres em `127.0.0.1` (uso interno; o participante não precisa vê-las).

## Subir

### Numa máquina nova — uma linha só

```bash
curl -fsSL https://raw.githubusercontent.com/BagualOps/adminforge-v1/main/docs/usability-study/lab/bootstrap.sh | bash
```

O `bootstrap.sh` clona o repo em `./adminforge-v1` (no diretório onde você rodar a one-liner — tudo a
nível de usuário, sem instalar nada no sistema) e roda o `prep.sh`. Customizável por env:
`ADMINFORGE_LAB_DIR` (destino — default `./adminforge-v1`), `ADMINFORGE_REPO_URL`, `ADMINFORGE_REPO_REF`.
Requisitos: `git`, `python3` ≥ 3.11, `docker` (com `docker compose` v2), `ssh`/`ssh-keygen` (OpenSSH client).

> **Segurança / reprodutibilidade.** `curl ... | bash` executa código remoto. Se preferir, baixe e
> inspecione antes: `curl -fsSLO <url>/bootstrap.sh && less bootstrap.sh && bash bootstrap.sh`. Para
> uma rodada do estudo, dá pra fixar numa tag/commit em vez de `main` (URL `.../<tag>/docs/...` +
> `ADMINFORGE_REPO_REF=<tag>`), pra todo mundo rodar exatamente a mesma versão.
>
> **Repo privado.** Hoje `BagualOps/adminforge-v1` é privado, então `raw.githubusercontent.com` só
> responde com autenticação — a one-liner anônima acima só funciona se o repo virar público. Em
> máquina sem credencial do GitHub, copie o repo pra lá (`rsync`/`scp`) e rode `./prep.sh` direto.

### Com o repo já clonado

```bash
cd docs/usability-study/lab
./prep.sh
```

`prep.sh` gera as chaves (em `keys/`, gitignored), cria o venv (`venv/`), sobe os 3 containers,
espera o sshd deles, e escreve `env.sh`. No fim imprime o ponto de entrada. Os IPs/portas da frota já constam na Tarefa 2 do roteiro
(o `prep.sh` os ecoa só pra você conferir). É idempotente.

## Sessão (o que o participante faz)

```bash
source <caminho-do-lab>/env.sh
adminforge --help          # autocomplete: Tab
```

- Chave pública da "Alice" (Tarefa 1): `alice.pub` (na pasta do lab).
- Estado do AdminForge: `state/` — começa vazio; `reset.sh` zera entre participantes.
- Histórico de comandos da sessão vai pra `archive/history-current` (via `HISTFILE` no `env.sh`);
  o `reset.sh` arquiva com timestamp.
- Servidores a cadastrar: `web-01 → 127.0.0.1:2201`, `web-02 → :2202`, `db-03 → :2203`.
  O `web-02` tem um `/etc/sudoers.d/zzz-legacy-deploy` semeado (drift pra Tarefa 8).

O facilitador usa o [`GUIA_FACILITADOR.md`](../GUIA_FACILITADOR.md) (critérios, dicas, folha de
observação) e os formulários (consentimento, perfil, SUS, TAM — companions).

## Entre participantes

```bash
./reset.sh
```

Arquiva o `history-current` e o `state/` em `archive/`, zera o estado, recria os containers.

## Conta dedicada pro participante (recomendado em vez de usar a conta do operador)

```bash
sudo useradd -m -s /bin/bash pesquisa
sudo -u pesquisa mkdir -p /home/pesquisa/.ssh && sudo chmod 700 /home/pesquisa/.ssh
# adicione a chave pública temporária do participante:
echo 'ssh-ed25519 AAAA... participante' | sudo tee /home/pesquisa/.ssh/authorized_keys
sudo chmod 600 /home/pesquisa/.ssh/authorized_keys && sudo chown -R pesquisa:pesquisa /home/pesquisa/.ssh
# faça o env.sh ser carregado no login dele:
echo "source $(pwd)/env.sh" | sudo tee -a /home/pesquisa/.bashrc
```

O participante entra com `ssh pesquisa@<host>` e já cai com o `adminforge` no PATH. Para um piloto
rápido, dá pra pular isso e o próprio operador dar `source env.sh` na conta dele.

## Derrubar tudo

```bash
docker compose down -v
# e, se quiser zerar de vez: rm -rf venv state keys archive alice.pub env.sh
```

> `keys/`, `state/`, `venv/`, `archive/`, `alice.pub`, `env.sh` são gerados em runtime e estão no
> `.gitignore` — não entram no repositório.
