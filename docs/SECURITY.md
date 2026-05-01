# Cuidados de segurança

> O AdminForge gerencia chaves SSH de administradores em servidores de produção. Esta seção lista o modelo de ameaças assumido, o que o sistema protege, o que **não** protege, e cuidados operacionais.

## Modelo de ameaças

| Ameaça | Mitigação |
|--------|-----------|
| Operador descuidado revoga acesso e esquece um servidor | `apply` calcula delta; remoção é propagada na próxima execução. |
| Admin sai da empresa | `admin disable` revoga todas as chaves; próximo `apply` remove dos servidores. |
| Adulteração retroativa do histórico | Cadeia SHA256 — `history verify` aponta primeiro divergente. |
| MitM no SSH em conexão recorrente | Host key armazenada em `state/known_hosts`; `ssh -o StrictHostKeyChecking=yes` rejeita divergência. |
| Concorrência (dois operadores rodando ao mesmo tempo) | Lockfile via `fcntl.flock`; segundo processo falha rápido. |
| Vazamento de leitura do `state/` por outro usuário do host | Diretório `0700`, arquivos `0600`. |
| Compromisso da chave privada do AdminForge | M-2: rotação. Hoje: trocar manualmente; questão em aberto na modelagem. |

## O que o AdminForge **não** protege

- **Logins dos admins nos servidores.** Isso é papel do `sshd` + `auditd` de cada máquina.
- **Comandos executados pelos admins.** Mesma resposta — auditoria nativa do host.
- **Vazamento de chave privada do admin** (Marina perdeu o laptop). Resposta: revogar fingerprint via `key revoke`, rodar `apply`. Speed-of-revocation depende do operador, não do AdminForge.
- **Ataques de cadeia de suprimentos** ao próprio Python ou ao OpenSSH. Mitigação fora de escopo da v1, mas note: a v1 zerou dependências de runtime, o que reduz a superfície de ataque drasticamente. Detalhes em [`ARCHITECTURE.md`](ARCHITECTURE.md#zero-deps).

## Permissões em disco

```bash
state/                 # 0700
├── admins/            # 0700
│   └── marina.json    # 0600
├── ...
└── history.jsonl      # 0600
```

O Store ajusta no momento de criar — verifique periodicamente:

```bash
find state/ \( -type d -not -perm 700 -o -type f -not -perm 600 \) -ls
```

## Chave SSH dedicada

A chave usada pelo Deployer deve ser **separada** da chave pessoal do Superadmin:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/adminforge_id -C "adminforge@cpd"
```

Razões:
- Quando rotacionar o Superadmin (vai embora, troca de máquina), não precisa rotacionar a chave de operação dos servidores.
- Restringir a chave nos servidores via `command=` ou `restrict` no `authorized_keys` do usuário de serviço.

Sugestão (servidor):

```
restrict,command="/usr/local/bin/adminforge-helper" ssh-ed25519 AAAA... adminforge@cpd
```

Refinar conforme necessidade — padrão atual confia no usuário de serviço com sudo.

## Host key (TOFU + RejectPolicy)

Cadastro:

```bash
adminforge server add web-01 --ip 10.0.0.10 --auto
# > host_key capturada: SHA256:...
# > Confirma o fingerprint? [y/N]: y
```

A partir daí, todas as conexões usam `ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=state/known_hosts`. Se a chave do servidor mudar, o SSH rejeita a conexão. **`StrictHostKeyChecking=no` é proibido na implementação.**

Trocou host key em manutenção?
1. Verifique a nova fingerprint via console / canal seguro.
2. `adminforge server remove <host>` e `server add <host>` de novo, ou (M-2) `server update-host-key`.

## Cadeia do histórico

Cada entrada de `history.jsonl` carrega `hash_anterior` e `hash` (SHA256 sobre o JSON canônico). Operações ilegais detectáveis:

- Alteração de qualquer campo (`status`, `superadmin`, lista de subações).
- Inserção, deleção ou reordenação de linhas.
- Truncamento (perda de entradas no final é detectada por `hash` orfão na próxima entrada — assumindo que a próxima foi feita antes).

Limitação: alguém com acesso de escrita ao `state/` pode **reescrever a cadeia inteira** consistente. Mitigação: backup periódico fora do host (ex.: `tar.gz` para storage segregado), ou — em M-3 — modo *pull* com Git assinado.

## Cifragem em repouso (opcional)

Por padrão, os arquivos JSON do estado são texto claro. Para cifrar seletivamente (chaves públicas não exigem, mas pode-se proteger e-mails, host keys, etc.):

- `age` ou `sops` por arquivo;
- chave gerenciada por `gpg-agent`/HSM/KMS conforme política do CPD.

Isso é roadmap M-2.

## Apply em lotes — limitar estrago

`apply` futuro (M-2) terá:
- Limite de paralelismo configurável.
- Taxa de falha máxima — interrompe o lote se ultrapassar (ex.: 50%), evita que erro sistêmico (DNS quebrado) propague chave errada para 600 máquinas.

Hoje (M-1) o `DryRunDeployer` simula falhas em testes; o `SSHDeployer` aplica subação a subação por servidor.

## Escopo de auditoria

| O que é auditado | Onde |
|------------------|------|
| Comandos do Superadmin no AdminForge | `state/history.jsonl` |
| Logins dos admins nos servidores | `sshd` (`/var/log/auth.log`) |
| Comandos dos admins logados | `auditd` de cada máquina |
| Inspeções operacionais do AdminForge | `state/history.jsonl` (status `leitura`) |

## Checklist operacional

- [ ] Chave dedicada do AdminForge criada e instalada nos usuários de serviço.
- [ ] `state/` em diretório com `0700`, arquivos `0600`.
- [ ] Backup periódico do `state/` (idealmente fora do host).
- [ ] Política de rotação anual da chave do AdminForge.
- [ ] `history verify` em ferramenta de monitoramento.
- [ ] Política de "revoga primeiro, investiga depois" para chaves comprometidas.
