# Quickstart

5 minutos do clone ao primeiro `apply`.

> **Placeholders.** Os nomes nos exemplos (`alice`, `bob`, `web-01`, `producao`, `sysadmins`, `<IP-DO-SERVIDOR>`, etc.) são genéricos — substitua pelos da sua frota.

## 1. Instalar

**Zero dependências de runtime.** Basta Python 3.11+ e cliente OpenSSH (presente em qualquer Linux).

```bash
git clone https://github.com/BagualOps/adminforge-v1.git
cd adminforge-v1

# Forma mais simples (sem venv, sem pip install):
python3 -m adminforge.cli.main --version
python3 -m adminforge.cli.main --help

# Para encurtar:
alias adminforge='python3 -m adminforge.cli.main'
```

Se preferir o comando `adminforge` instalado de verdade, qualquer uma das opções abaixo:

```bash
pipx install .                       # isolado, recomendado
pip install --user .                 # no PATH do usuario
pip install -e . --break-system-packages   # ultimo recurso em distros estritas
```

Para rodar a suíte de testes (depende de pytest):

```bash
pip install -e .[dev]
pytest -q
```

## 2. Configurar diretório de estado

Por padrão, o estado vive em `./state/`. Para usar outro diretório:

```bash
export ADMINFORGE_STATE=/var/lib/adminforge/state
```

O diretório é criado automaticamente. Permissões: `0700` no diretório, `0600` nos arquivos.

## 3. Chave SSH e usuário de serviço

O AdminForge precisa de **um usuário Linux** em cada servidor gerenciado, com **uma chave SSH** instalada e **sudo sem senha**. Há duas formas de chegar lá; escolha conforme seu cenário.

### Opção A — Usuário dedicado (recomendado para frota nova)

Crie uma chave nova só para o AdminForge — não reaproveite a sua pessoal.

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/adminforge_id -C "adminforge@cpd"

export ADMINFORGE_SSH_KEY=~/.ssh/adminforge_id
export ADMINFORGE_SSH_USER=adminforge
```

Bootstrap nos servidores:

- **Imagem nova / cloud-init.** Inclua no `user-data`:

  ```yaml
  #cloud-config
  users:
    - name: adminforge
      sudo: ALL=(ALL) NOPASSWD:ALL
      shell: /bin/bash
      ssh_authorized_keys:
        - ssh-ed25519 AAAA... adminforge@cpd
  ```

- **Servidor existente.** Uma vez, manualmente:

  ```bash
  ssh root@host bash <<'EOF'
  useradd -m -s /bin/bash adminforge
  echo 'adminforge ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/adminforge
  chmod 0440 /etc/sudoers.d/adminforge
  visudo -c
  install -d -m 700 -o adminforge -g adminforge /home/adminforge/.ssh
  echo "$(cat ~/.ssh/adminforge_id.pub)" \
      | install -m 600 -o adminforge -g adminforge /dev/stdin /home/adminforge/.ssh/authorized_keys
  EOF
  ```

Vantagem: separa identidade do operador da identidade da ferramenta. Quando você sair, a chave dele continua válida para a ferramenta.

### Opção B — Usuário existente (rápido para testar / hosts compartilhados)

Você já tem SSH na máquina como `seu_user` com chave pessoal e sudo? Dá para reaproveitar.

```bash
export ADMINFORGE_SSH_KEY=~/.ssh/sua_chave_existente
export ADMINFORGE_SSH_USER=seu_user
```

Pré-requisitos no servidor:

1. Sua chave pública já está em `~/seu_user/.ssh/authorized_keys` (você já loga sem senha).
2. `seu_user` tem `sudo` (idealmente `NOPASSWD` para `useradd`, escrita em `/etc/sudoers.d/`, edição de `~/<admin>/.ssh/authorized_keys`).
3. Você concorda que o histórico do AdminForge vai gravar `seu_user` como executor das ações.

Para reduzir surpresas com `sudo` que pede senha durante o `apply`, garanta uma regra mínima:

```bash
ssh seu_user@host "echo '$USER ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/adminforge-bootstrap >/dev/null && sudo visudo -c"
```

Se você não quer que o AdminForge crie contas Unix automaticamente (caso de hosts compartilhados onde UID/GID são gerenciados fora da ferramenta — LDAP, NIS, etc.), desabilite a criação automática:

```bash
export ADMINFORGE_CREATE_UNIX_USER=false
```

Nesse modo, o `apply` falha com mensagem clara se o usuário Linux não existir, em vez de tentar `useradd`.

### Verificação rápida do bootstrap

Antes do primeiro `apply`, confirme que a sessão SSH funciona com a chave que o AdminForge vai usar:

```bash
ssh -i $ADMINFORGE_SSH_KEY -o BatchMode=yes $ADMINFORGE_SSH_USER@<servidor> 'whoami; sudo -n whoami'
```

Esperado: o usuário e `root` na segunda linha. Se a segunda linha pedir senha ou der erro, ajuste o sudoers antes de seguir.

> **Por que o AdminForge não faz esse bootstrap sozinho?** Porque ele precisa da chave **já dentro** do servidor para entrar — é o problema clássico do "ovo e galinha". Bootstrap é o passo único pré-AdminForge; depois disso, a ferramenta cuida de todas as chaves dos usuários reais.

## 4. Cadastros

```bash
adminforge user add --username alice --name "Alice Silva" --email alice@empresa.com
adminforge user key add --username alice --file ~/.ssh/alice.pub

adminforge user-group create --name sysadmins
adminforge user-group add-member --group sysadmins --username alice

adminforge server add --hostname web-01 --ip 10.0.0.10 --auto
# > host_key capturada: SHA256:abc...
# > Confirma o fingerprint? [y/N]: y
# > OK   server add web-01  (OP-0007)

adminforge server-group create --name producao
adminforge server-group add-member --group producao --hostname web-01

adminforge permission grant --user-group sysadmins --server-group producao --level sudo
```

## 5. Preview e apply

```bash
adminforge preview
# i  1 subacoes em 1 servidores
#
# web-01
#   + adicionar_chave    alice:SHA256:abc...    sudo

adminforge apply
# Aplicar agora? [y/N]: y
#   OK   web-01    adicionar_chave    alice:SHA256:abc...
# operacao: OP-0008
#   status: SUCESSO
# sucessos: 1
#   falhas: 0
```

## 6. Auditoria

```bash
adminforge history list
adminforge history show --id OP-0008
adminforge history verify       # checa cadeia SHA256
```

Inspeção operacional do servidor (read-only):

```bash
adminforge audit server --hostname web-01
adminforge audit server --hostname web-01 --user tomcat
```

## Próximos passos

- Cookbook completo por UC: [`USAGE.md`](USAGE.md)
- Variáveis de ambiente e layout do estado: [`CONFIG.md`](CONFIG.md)
- Decisões de arquitetura: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Cuidados de segurança: [`SECURITY.md`](SECURITY.md)
