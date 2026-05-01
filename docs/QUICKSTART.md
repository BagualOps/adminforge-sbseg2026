# Quickstart

5 minutos do clone ao primeiro `apply`.

## 1. Instalar

```bash
git clone https://github.com/BagualOps/adminforge-v1.git
cd adminforge-v1
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Verifique:

```bash
adminforge --version
adminforge --help
```

## 2. Configurar diretório de estado

Por padrão, o estado vive em `./state/`. Para usar outro diretório:

```bash
export ADMINFORGE_STATE=/var/lib/adminforge/state
```

O diretório é criado automaticamente. Permissões: `0700` no diretório, `0600` nos arquivos.

## 3. Chave SSH dedicada

Crie a chave que o AdminForge usará para conectar nos servidores. **Não use a sua chave pessoal.**

```bash
ssh-keygen -t ed25519 -f ~/.ssh/adminforge_id -C "adminforge@cpd"
export ADMINFORGE_SSH_KEY=~/.ssh/adminforge_id
export ADMINFORGE_SSH_USER=adminforge   # usuario de servico nos servidores
```

A chave pública precisa estar instalada no usuário de serviço (`adminforge` por padrão) de cada servidor antes do primeiro `apply`. Para servidores novos, use `cloud-init` ou faça uma vez manualmente — esta é uma das questões em aberto da modelagem (M-1, item 2 de "Questões em aberto").

## 4. Cadastros

```bash
adminforge admin add marina --nome "Marina Silva" --email marina@empresa.com
adminforge key add marina --file ~/.ssh/marina.pub

adminforge group create sysadmins
adminforge group add-member sysadmins marina

adminforge server add web-01 --ip 10.0.0.10 --auto
# > host_key capturada: SHA256:abc...
# > Confirma o fingerprint? [y/N]: y
# > OK   server add web-01  (OP-0007)

adminforge server-group create producao
adminforge server-group add-member producao web-01

adminforge grant sysadmins producao --nivel sudo
```

## 5. Preview e apply

```bash
adminforge preview
# i  1 subacoes em 1 servidores
#
# web-01
#   + adicionar_chave    marina:SHA256:abc...    sudo

adminforge apply
# Aplicar agora? [y/N]: y
#   OK   web-01    adicionar_chave    marina:SHA256:abc...
# operacao: OP-0008
#   status: SUCESSO
# sucessos: 1
#   falhas: 0
```

## 6. Auditoria

```bash
adminforge history list
adminforge history show OP-0008
adminforge history verify       # checa cadeia SHA256
```

Inspeção operacional do servidor (read-only):

```bash
adminforge audit server web-01
adminforge audit server web-01 --user tomcat
```

## Próximos passos

- Cookbook completo por UC: [`USAGE.md`](USAGE.md)
- Variáveis de ambiente e layout do estado: [`CONFIG.md`](CONFIG.md)
- Decisões de arquitetura: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Cuidados de segurança: [`SECURITY.md`](SECURITY.md)
