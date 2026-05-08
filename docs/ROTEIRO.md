# Guia de operação

Como usar o AdminForge na sua frota — desde o primeiro servidor até a rotina diária. Não é um roteiro de teste descartável: cada passo aqui é uma operação real que você vai repetir no dia-a-dia.

---

## 0. Pré-requisitos

Na sua máquina (de onde você opera):

- Python 3.11+
- Cliente OpenSSH (`ssh`, `ssh-keyscan`)
- `git`

Em cada servidor da frota:

- SSH habilitado
- Acesso `sudo` para você entrar uma vez e bootstrappar; depois o AdminForge usa o usuário de serviço dele

---

## 1. Instalar (uma vez)

```bash
git clone https://github.com/BagualOps/adminforge-v1.git
cd adminforge-v1
alias af='python3 -m adminforge.cli.main'
```

Sem `pip install`, sem `venv`. Zero deps de runtime. Para deixar `af` permanente, ponha o alias no seu `~/.bashrc` ou `~/.zshrc`.

---

## 2. Configurar onde mora o estado

```bash
mkdir -p ~/.adminforge
export ADMINFORGE_STATE=~/.adminforge/state
export ADMINFORGE_SUPERADMIN=$USER
```

O estado é um diretório com JSONs e o `history.jsonl`. Tudo `0700`/`0600`. **Não comite essa pasta** — contém dados sensíveis da sua frota.

> Faça backup periódico do `state/`: perdeu-o, perdeu o registro do que está declarado.

---

## 3. Gerar a chave SSH dedicada do AdminForge

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/adminforge_id -C "adminforge@$(hostname)"
export ADMINFORGE_SSH_KEY=~/.ssh/adminforge_id
export ADMINFORGE_SSH_USER=adminforge
```

> **Não reaproveite sua chave pessoal.** Quando você sair da empresa, sua chave pessoal será revogada — mas a chave do AdminForge precisa continuar válida para o próximo operador.

---

## 4. Bootstrappar o acesso ao servidor (uma vez por servidor)

O AdminForge precisa de **um usuário Linux no servidor com `sudo NOPASSWD` e uma chave SSH instalada**. Há dois cenários, escolha conforme seu contexto:

---

### Cenário 1 — Você controla totalmente o servidor (VM, VPS, hardware seu)

Crie um usuário **dedicado** chamado `adminforge`. É a forma mais limpa: separa identidade do operador da identidade da ferramenta.

#### 1a. Servidor existente, via SSH

> **Heredoc com aspas (`<<'EOF'`) é importante** — sem aspas, `$(...)` é expandido localmente e pode pegar a chave errada. Pra evitar a armadilha completamente, copie a pubkey antes:

**Substitua `MEU_USER` e `MEU_HOST` pelos seus valores antes de colar:**

```bash
scp ~/.ssh/adminforge_id.pub MEU_USER@MEU_HOST:/tmp/adminforge.pub

ssh MEU_USER@MEU_HOST bash -s <<'EOF'
set -ex
sudo useradd -m -s /bin/bash adminforge 2>/dev/null || true
echo 'adminforge ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/adminforge >/dev/null
sudo chmod 0440 /etc/sudoers.d/adminforge
sudo visudo -c >/dev/null
sudo install -d -m 700 -o adminforge -g adminforge /home/adminforge/.ssh
sudo install -m 600 -o adminforge -g adminforge /tmp/adminforge.pub /home/adminforge/.ssh/authorized_keys
rm -f /tmp/adminforge.pub
EOF
```

#### 1b. VM nova, via cloud-init `user-data`

```yaml
#cloud-config
users:
  - name: adminforge
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... adminforge@operador
```

#### Verifique antes de continuar

```bash
ssh -i ~/.ssh/adminforge_id -o BatchMode=yes adminforge@MEU_HOST 'whoami; sudo -n whoami'
# Esperado: adminforge / root
```

Configure as variáveis com o user dedicado:

```bash
export ADMINFORGE_SSH_USER=adminforge
export ADMINFORGE_SSH_KEY=~/.ssh/adminforge_id
```

---

### Cenário 2 — Servidor compartilhado (você só pode logar como você mesmo)

Comum em CPDs/labs onde o `sshd_config` tem `AllowUsers <lista-fixa>` e você não tem autoridade pra adicionar um user novo. Aqui você **reusa sua própria conta** (que já está na lista) como service user do AdminForge.

**Pré-requisitos:**

1. Sua conta no servidor tem `sudo NOPASSWD`. Confirme:

   ```bash
   ssh -o BatchMode=yes MEU_USER@MEU_HOST 'sudo -n whoami'
   # Esperado: root
   # Se pedir senha: precisa configurar NOPASSWD pra seu user (peça pro admin do CPD).
   ```

2. **As contas Unix dos usuários gerenciados já existem no servidor** — você não pode criar contas novas (quem mantém isso é o admin do CPD via LDAP/manual). O AdminForge vai instalar chaves e sudoers nelas, **não** criar.

Configure as variáveis apontando pro seu user e desligando a criação automática de contas. **Ajuste os valores marcados com `# AJUSTE` antes de colar:**

```bash
export ADMINFORGE_SSH_USER=$USER                            # AJUSTE se seu user no servidor for outro
export ADMINFORGE_SSH_KEY=~/.ssh/nome_do_arquivo_da_chave   # AJUSTE para o nome real (geralmente em ~/.ssh/)
export ADMINFORGE_CREATE_UNIX_USER=false
```

> Pra descobrir qual chave seu SSH usa para esse host:
> ```bash
> ssh -G servidor | grep -i identityfile
> ```
> (Substitua `servidor` pelo hostname real.) Ele lista os caminhos das chaves consultadas, default ou via `~/.ssh/config`. Pegue a primeira que existe e funciona.

Com `ADMINFORGE_CREATE_UNIX_USER=false`, o `apply` falha com mensagem clara se algum usuário cadastrado não existir como conta Unix no host — em vez de tentar `useradd`.

Não há bootstrap adicional aqui: a configuração SSH+sudo do seu user já é o "bootstrap".

> **Diagnóstico rápido se a Opção 1 falha mesmo com a chave instalada.** Se `ssh -i ... adminforge@<host>` der `Permission denied (publickey,password)` mas o `authorized_keys` está correto, provavelmente é `AllowUsers` no sshd. Confirma com:
>
> ```bash
> ssh MEU_USER@MEU_HOST 'sudo journalctl -u ssh -n 20 --no-pager | grep AllowUsers'
> ```
>
> Se aparecer `User adminforge ... not allowed because not listed in AllowUsers`, vá pro Cenário 2 (ou peça acesso pra incluir `adminforge` no `AllowUsers`).

---

## 5. Cadastrar sua frota e sua equipe

### 5.1 Servidores

**Substitua `MEU_HOST_IP` pelo IP real do seu servidor antes de executar.** Pode usar hostname também (ex: `--ip 192.0.2.50` ou `--ip srv01.empresa.com`).

```bash
af server add --hostname prod-web-01 --ip MEU_HOST_IP --auto
# > host_key capturada: SHA256:...
# > Confirma o fingerprint? [y/N]: y

# Repita para cada servidor da frota, com seu apelido e IP/hostname:
# af server add --hostname prod-web-02 --ip OUTRO_IP --auto
# af server add --hostname prod-db-01 --ip MAIS_UM_IP --auto

af server list
```

Confira a fingerprint contra um canal seguro (console do hypervisor, doc do CPD, ssh-keyscan paralelo) antes de aceitar.

> Se o `--auto` travar/falhar com timeout, é porque o IP não responde ou o `ssh-keyscan` não consegue alcançar a porta 22. Confirme que dá pra logar com `ssh MEU_USER@MEU_HOST_IP` antes.

### 5.2 Grupos de servidor

```bash
af server-group create --name web
af server-group add-member --group web --hostname prod-web-01
af server-group add-member --group web --hostname prod-web-02

af server-group create --name banco
af server-group add-member --group banco --hostname prod-db-01

af server-group create --name producao
af server-group add-member --group producao --hostname prod-web-01
af server-group add-member --group producao --hostname prod-web-02
af server-group add-member --group producao --hostname prod-db-01
```

### 5.3 Usuários reais da equipe

```bash
af user add --username ana --name "Ana Souza" --email ana@empresa.com
af user add --username bruno --name "Bruno Lima" --email bruno@empresa.com
af user add --username diego --name "Diego Pereira" --email diego@empresa.com
af user list
```

> **Atenção em servidor compartilhado (Cenário 2 do passo 4):** o `username` aqui precisa **bater com uma conta Unix que já existe** no servidor. Cadastrar `bruno` no AdminForge enquanto não há `bruno` no `/etc/passwd` do host vai fazer o `apply` falhar com mensagem clara. Em servidor próprio (Cenário 1), o AdminForge cria a conta no primeiro `apply`.

### 5.4 Chaves públicas SSH

Pegue o `.pub` de cada usuário (Slack, email, drive interno) e:

```bash
af user key add --username ana --file /caminho/para/ana.pub
af user key add --username bruno --string "ssh-ed25519 AAAA... bruno@laptop"
af user key add --username diego --file /caminho/para/diego.pub
```

Aceita `ssh-ed25519`, `ssh-rsa`, `ecdsa-sha2-*`. Fingerprint armazenado é SHA256.

### 5.5 Grupos de usuários por função

```bash
af user-group create --name sysadmins
af user-group add-member --group sysadmins --username ana
af user-group add-member --group sysadmins --username bruno

af user-group create --name dba
af user-group add-member --group dba --username diego
af user-group add-member --group dba --username ana          # Ana faz os dois papéis
```

### 5.6 Conceder acesso

```bash
af grant --user-group sysadmins --server-group web --level sudo
af grant --user-group sysadmins --server-group banco --level shell    # leitura/troubleshooting
af grant --user-group dba --server-group banco --level sudo
```

### 5.7 Ver e aplicar

```bash
af preview                  # delta agrupado por servidor
af apply                    # confirma; executa via SSH
```

> O primeiro `apply` cria as contas Unix dos usuários gerenciados, instala as chaves em `~/<user>/.ssh/authorized_keys` (envoltas em markers `# BEGIN/END adminforge: <ref>`), e escreve `/etc/sudoers.d/adminforge-<user>` para os de nível `sudo` (validado por `visudo -cf` antes do move).

---

## 6. Operação diária

### Alguém entrou na equipe

```bash
af user add --username julia --name "Julia Mendes" --email julia@empresa.com
af user key add --username julia --file /tmp/julia.pub
af user-group add-member --group sysadmins --username julia
af apply
```

### Alguém saiu da empresa

```bash
af user disable --username bruno --yes
af apply                    # remove a chave do bruno de TODOS os servidores
```

A conta Unix `bruno` permanece nos servidores (apaga arquivos dele em todos é decisão sua). O acesso some no `apply`. Se quiser remover a conta também:

```bash
ssh -i ~/.ssh/adminforge_id adminforge@MEU_HOST 'sudo userdel -r bruno'
# Atenção: -r apaga /home/bruno
```

### Alguém trocou de função

```bash
af user-group remove-member --group sysadmins --username ana
af user-group add-member --group dba --username ana
af apply
```

### Chave comprometida (perda de laptop, vazamento)

```bash
af user key list --username ana
af user key revoke --fingerprint SHA256:abc...     # marca como revogada
af apply                        # remove só essa chave de todos os servidores

# Cadastra a chave nova:
af user key add --username ana --file /caminho/para/ana-novo-laptop.pub
af apply
```

### Servidor novo entrou na frota

```bash
af server add --hostname prod-web-03 --ip 10.0.0.12 --auto
af server-group add-member --group web --hostname prod-web-03
af apply                        # instala chaves de todos do grupo 'sysadmins' nele
```

### Conceder acesso pontual a um grupo novo

```bash
af user-group create --name monitoring
af user-group add-member --group monitoring --username carla   # carla já cadastrada como user
af grant --user-group monitoring --server-group producao --level shell
af apply
```

### Auditar quem tem acesso a um servidor

```bash
af server show --hostname prod-web-01      # chaves declaradas (ref + nivel)
af audit server --hostname prod-web-01     # leitura via SSH: usuários + serviços ativos
af audit server --hostname prod-web-01 --user tomcat
# Avisa se 'tomcat' existe como conta mas não há tomcat.service rodando
```

---

## 7. Histórico

```bash
af history list             # últimas 50 operações
af history show --id OP-0042     # detalhes
af history failed           # só falhas e parciais
af history verify           # valida cadeia SHA256
```

Coloque `af history verify` no seu monitoring. Se sair com erro, alguém adulterou o `history.jsonl` e o comando aponta o ID da primeira entrada divergente.

---

## 8. Quando algo dá errado

### `apply` parou no meio com erro de SSH

A subação que falhou fica anotada no histórico; `chaves_instaladas` daquele servidor não muda. No próximo `apply`, o delta naturalmente identifica o que faltou — basta rodar de novo.

```bash
af history failed
af history show --id OP-XXXX        # vê qual subação falhou
# corrige o problema (servidor offline, conexão, etc.)
af apply                       # retentativa só do que faltou
```

### Servidor mudou de host_key (manutenção, reinstalação)

```bash
af server remove --hostname prod-web-01
af server add --hostname prod-web-01 --ip 10.0.0.10 --auto    # confirma a nova fingerprint
af apply
```

### Outra instância do AdminForge rodando

```
ERRO outra instância do AdminForge está em execução
```

Lockfile `state/.lock` em uso. Verifique se você tem outro `af apply` em andamento. Travado por processo morto:

```bash
rm $ADMINFORGE_STATE/.lock
```

### O que está nos servidores diverge do declarado?

```bash
af server show --hostname prod-web-01      # declarado
af audit server --hostname prod-web-01     # real (read-only via SSH)
```

`apply verify` (compara declarado × real automaticamente) é roadmap M-2.

---

## 9. Backup do estado

O diretório `state/` é a fonte da verdade declarada. Perdê-lo é perder o controle do que está declarado.

```bash
# numa cron diária
tar -czf adminforge-state-$(date +%F).tar.gz -C ~/.adminforge state/
# enviar pro seu storage seguro
```

> M-3 do roadmap migra o estado para repositório Git assinado com modo *pull* nos servidores — backup vira lateral.

---

## Próximos passos

- Comandos detalhados por caso de uso: [`USAGE.md`](USAGE.md)
- Variáveis de ambiente e schemas: [`CONFIG.md`](CONFIG.md)
- Modelo de ameaças: [`SECURITY.md`](SECURITY.md)
- Decisões de arquitetura: [`ARCHITECTURE.md`](ARCHITECTURE.md)

> **Sobre testes automatizados.** O lab Docker (`infra/testlab/`) e o teste de integração (`tests/integration/test_lab.py`) existem para CI e desenvolvimento. Você não precisa interagir com eles para usar o AdminForge em produção.
