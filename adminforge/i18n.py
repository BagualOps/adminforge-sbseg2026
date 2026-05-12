"""Localizacao leve da CLI (sem dependencias).

O texto-fonte em ingles e a *chave*; o catalogo `pt` fornece a traducao, com
fallback para o proprio texto-fonte quando a chave nao esta no catalogo. Assim o
ingles (padrao) custa zero e uma chave sem traducao degrada para ingles em vez de
quebrar.

Mensagens com valores interpolados usam placeholders no estilo str.format
(`{x}`), nunca f-strings, para que o template possa ser traduzido:

    ui.fail(t("user {u} does not exist").format(u=username))

Idioma: env var ADMINFORGE_LANG (`en` | `pt` | `pt_BR`...); se ausente, cai para
LC_ALL / LC_MESSAGES / LANG; default `en`. Resolvido a cada chamada de t() para
ser sensivel a mudanca de env em testes; set_lang() permite forcar.
"""
from __future__ import annotations

import os

_OVERRIDE: str | None = None


def _normalize(raw: str) -> str:
    return "pt" if raw.lower().startswith("pt") else "en"


def _resolve_lang() -> str:
    if _OVERRIDE is not None:
        return _OVERRIDE
    raw = (
        os.environ.get("ADMINFORGE_LANG")
        or os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or ""
    )
    return _normalize(raw) if raw else "en"


def set_lang(code: str | None) -> None:
    """Forca o idioma (usado em testes). `None` volta a resolucao automatica por env."""
    global _OVERRIDE
    _OVERRIDE = None if code is None else _normalize(code)


def t(msg: str) -> str:
    lang = _resolve_lang()
    if lang == "en":
        return msg
    return _CATALOGS.get(lang, {}).get(msg, msg)


# alias curto, no estilo gettext
_ = t


# ---------------------------------------------------------------------------
# Catalogos. Chave = texto-fonte em ingles (exatamente como aparece no codigo).
# ---------------------------------------------------------------------------
_CATALOGS: dict[str, dict[str, str]] = {
    "pt": {
        # ---- parser: descricao geral e epilogos ----
        "AdminForge - manages who has privileged access (SSH keys and sudo) on a fleet of "
        "Linux servers.\n\n"
        "You edit the desired state with these commands; 'apply' pushes the changes to the "
        "servers over SSH. Every command goes into history.jsonl.\n\n"
        "Every command has its own --help, e.g. 'adminforge user --help', "
        "'adminforge permission grant --help'.":
        "AdminForge - gerencia quem tem acesso privilegiado (chaves SSH e sudo) numa frota de "
        "servidores Linux.\n\n"
        "Voce edita o estado desejado com estes comandos; o 'apply' leva as mudancas para os "
        "servidores via SSH. Todo comando vai para o history.jsonl.\n\n"
        "Cada comando tem seu proprio --help, ex.: 'adminforge user --help', "
        "'adminforge permission grant --help'.",

        "EXAMPLES\n"
        "  adminforge user add --username marina --name \"Marina Silva\" --email marina@empresa.com --key-file ~/.ssh/marina.pub\n"
        "  adminforge user-group create --name sysadmins\n"
        "  adminforge user-group add-member --group sysadmins --username marina\n"
        "  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto\n"
        "  adminforge server-group create --name producao\n"
        "  adminforge server-group add-member --group producao --hostname web-01\n"
        "  adminforge permission grant --user-group sysadmins --server-group producao --level sudo\n"
        "  adminforge preview\n"
        "  adminforge apply\n"
        "\n"
        "DOCS\n"
        "  Detailed model: docs/modelagem-v1.pdf\n"
        "  Use-case cookbook: docs/USAGE.md\n":
        "EXEMPLOS\n"
        "  adminforge user add --username marina --name \"Marina Silva\" --email marina@empresa.com --key-file ~/.ssh/marina.pub\n"
        "  adminforge user-group create --name sysadmins\n"
        "  adminforge user-group add-member --group sysadmins --username marina\n"
        "  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto\n"
        "  adminforge server-group create --name producao\n"
        "  adminforge server-group add-member --group producao --hostname web-01\n"
        "  adminforge permission grant --user-group sysadmins --server-group producao --level sudo\n"
        "  adminforge preview\n"
        "  adminforge apply\n"
        "\n"
        "DOCUMENTACAO\n"
        "  Modelagem detalhada: docs/modelagem-v1.pdf\n"
        "  Receituario por caso de uso: docs/USAGE.md\n",

        "Examples:\n"
        "  adminforge permission grant --user-group sa --server-group prod --level sudo\n"
        "  adminforge permission revoke --user-group sa --server-group prod\n"
        "  adminforge permission list\n"
        "  adminforge permission show --user alice":
        "Exemplos:\n"
        "  adminforge permission grant --user-group sa --server-group prod --level sudo\n"
        "  adminforge permission revoke --user-group sa --server-group prod\n"
        "  adminforge permission list\n"
        "  adminforge permission show --user alice",

        "Examples:\n"
        "  adminforge permission show --user alice\n"
        "  adminforge permission show --user-group sysadmins\n"
        "  adminforge permission show --server-group producao":
        "Exemplos:\n"
        "  adminforge permission show --user alice\n"
        "  adminforge permission show --user-group sysadmins\n"
        "  adminforge permission show --server-group producao",

        "Examples:\n"
        "  adminforge sudo-profile create --name read-logs --command /bin/journalctl --command '/bin/cat /var/log/*'\n"
        "  adminforge sudo-profile list\n"
        "  adminforge permission grant --user-group monitoring --server-group prod --level sudo --profile read-logs":
        "Exemplos:\n"
        "  adminforge sudo-profile create --name read-logs --command /bin/journalctl --command '/bin/cat /var/log/*'\n"
        "  adminforge sudo-profile list\n"
        "  adminforge permission grant --user-group monitoring --server-group prod --level sudo --profile read-logs",

        "Examples:\n"
        "  adminforge user add --username marina --name 'Marina' --email marina@empresa.com --key-file ~/.ssh/marina.pub\n"
        "  adminforge user key add --username marina --file ~/.ssh/marina.pub   # ou em dois passos\n"
        "  adminforge user disable --username marina":
        "Exemplos:\n"
        "  adminforge user add --username marina --name 'Marina' --email marina@empresa.com --key-file ~/.ssh/marina.pub\n"
        "  adminforge user key add --username marina --file ~/.ssh/marina.pub   # ou em dois passos\n"
        "  adminforge user disable --username marina",

        "Examples:\n"
        "  adminforge user-group create --name sysadmins\n"
        "  adminforge user-group add-member --group sysadmins --username alice bob carla\n"
        "  adminforge user-group remove-member --group sysadmins --username bob":
        "Exemplos:\n"
        "  adminforge user-group create --name sysadmins\n"
        "  adminforge user-group add-member --group sysadmins --username alice bob carla\n"
        "  adminforge user-group remove-member --group sysadmins --username bob",

        "Examples:\n"
        "  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto\n"
        "  adminforge server show --hostname web-01\n"
        "\n"
        "About --auto and the fingerprint: see docs/USAGE.md (UC-4).":
        "Exemplos:\n"
        "  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto\n"
        "  adminforge server show --hostname web-01\n"
        "\n"
        "Sobre --auto e o fingerprint: ver docs/USAGE.md (UC-4).",

        "Examples:\n"
        "  adminforge server-group create --name producao\n"
        "  adminforge server-group add-member --group producao --hostname web-01 web-02 db-03":
        "Exemplos:\n"
        "  adminforge server-group create --name producao\n"
        "  adminforge server-group add-member --group producao --hostname web-01 web-02 db-03",

        # ---- parser: help= de comandos e flags ----
        "State directory (default: ./state or $ADMINFORGE_STATE).":
            "Diretorio de estado (padrao: ./state ou $ADMINFORGE_STATE).",
        "Register, lifecycle and SSH keys of users.":
            "Cadastro, ciclo de vida e chaves SSH de usuarios.",
        "Register a new user (optionally with their SSH key).": "Cadastra um novo usuario (opcionalmente ja com a chave SSH dele).",
        "Also register this .pub file as the user's key.": "Tambem registra este arquivo .pub como chave do usuario.",
        "Also register this full key string as the user's key.": "Tambem registra esta chave (string completa) como chave do usuario.",
        "List users.": "Lista usuarios.",
        "Show user details.": "Mostra detalhes do usuario.",
        "Disable user (revokes all keys).": "Desabilita o usuario (revoga todas as chaves).",
        "Register and revoke user SSH keys.": "Cadastra e revoga chaves SSH de usuarios.",
        "Register an SSH key.": "Cadastra uma chave SSH.",
        "Path to a .pub file.": "Caminho para um arquivo .pub.",
        "Paste the full key.": "Cole a chave inteira.",
        "Revoke a key by fingerprint.": "Revoga uma chave pelo fingerprint.",
        "List user keys.": "Lista as chaves do usuario.",
        "User groups.": "Grupos de usuarios.",
        "one or more usernames (separated by space or comma)":
            "um ou mais usernames (separados por espaco ou virgula)",
        "Server registration.": "Cadastro de servidores.",
        "Register a server (TOFU host_key).": "Cadastra um servidor (host_key por TOFU).",
        "Server IPv4.": "IPv4 do servidor.",
        "ssh-keyscan output, e.g. 'ssh-ed25519 AAAA...'":
            "saida do ssh-keyscan, ex.: 'ssh-ed25519 AAAA...'",
        "Capture host_key via ssh-keyscan.": "Captura a host_key via ssh-keyscan.",
        "Server groups.": "Grupos de servidores.",
        "one or more hostnames (separated by space or comma)":
            "um ou mais hostnames (separados por espaco ou virgula)",
        "Manage permissions: grant / revoke / list / show.":
            "Gerencia permissoes: grant / revoke / list / show.",
        "Grant access from a user-group to a server-group.":
            "Concede acesso de um user-group a um server-group.",
        "Sudo profile name (only with --level sudo); without it, grants NOPASSWD:ALL.":
            "Nome do sudo-profile (so com --level sudo); sem ele, concede NOPASSWD:ALL.",
        "Revoke access between two groups.": "Revoga o acesso entre dois grupos.",
        "Skip confirmation.": "Pula a confirmacao.",
        "List all permissions.": "Lista todas as permissoes.",
        "Reverse query: which servers a user effectively reaches, or which grants reach a group.":
            "Consulta reversa: a que servidores um usuario efetivamente chega, ou que concessoes alcancam um grupo.",
        "Manage named sudo profiles (allowed commands per role).":
            "Gerencia sudo-profiles nomeados (comandos permitidos por papel).",
        "Create a sudo profile with one or more absolute commands.":
            "Cria um sudo-profile com um ou mais comandos absolutos.",
        "Absolute path to allow (repeat).":
            "Caminho absoluto a permitir (pode repetir).",
        "List sudo profiles.": "Lista os sudo-profiles.",
        "Show commands of a sudo profile.": "Mostra os comandos de um sudo-profile.",
        "Delete a sudo profile (must be unused).":
            "Apaga um sudo-profile (precisa estar sem uso).",
        "Quick overview: counts, pending changes, last operation, history chain.":
            "Visao rapida: contagens, pendencias, ultima operacao, cadeia do historico.",
        "List the full declared state (users, groups, servers, permissions).":
            "Lista o estado declarado completo (usuarios, grupos, servidores, permissoes).",
        "Show the delta without applying.": "Mostra o delta sem aplicar.",
        "Apply the delta to servers via SSH.": "Aplica o delta nos servidores via SSH.",
        "Use the fake Deployer.": "Usa o Deployer falso (dry-run).",
        "Show authorized_keys before/after diff per user.":
            "Mostra o diff antes/depois do authorized_keys por usuario.",
        "Compare declared chaves_instaladas vs real authorized_keys.":
            "Compara o chaves_instaladas declarado vs o authorized_keys real.",
        "Query operational history.": "Consulta o historico operacional.",
        "Operational audit (read-only via SSH).":
            "Auditoria operacional (somente leitura via SSH).",
        "Inspect users, groups, sudoers and services of the server.":
            "Inspeciona usuarios, grupos, sudoers e servicos do servidor.",
        "Highlight occurrences of this user.": "Destaca ocorrencias deste usuario.",
        "Filter groups by substring.": "Filtra grupos por substring.",
        "Highlight occurrences of this service.": "Destaca ocorrencias deste servico.",
        "Show only human users (UID >= 1000).": "Mostra so usuarios humanos (UID >= 1000).",

        # ---- main.py: mensagens de erro (ui.fail) ----
        "user {u} does not exist": "usuario {u} nao existe",
        "use --file OR --string, not both": "use --file OU --string, nao os dois",
        "provide --file or --string": "informe --file ou --string",
        "could not read key file {f}: {e}": "nao foi possivel ler o arquivo de chave {f}: {e}",
        "failed to capture host_key: {e}": "falha ao capturar a host_key: {e}",
        "provide --host-key or --auto": "informe --host-key ou --auto",
        "server {h} does not exist": "servidor {h} nao existe",
        "sudo-profile {n} does not exist": "sudo-profile {n} nao existe",
        "user-group {g} does not exist": "user-group {g} nao existe",
        "server-group {g} does not exist": "server-group {g} nao existe",
        "operation {i} does not exist": "operacao {i} nao existe",
        "provide one of: --user, --user-group, --server-group":
            "informe um de: --user, --user-group, --server-group",
        "chain broken: {e}": "cadeia quebrada: {e}",

        # ---- main.py: headings, info, ok, warn, prompts ----
        "operation cancelled": "operacao cancelada",
        "registration aborted": "cadastro abortado",
        "apply cancelled": "apply cancelado",
        "Disable {u} and revoke their keys? (apply removes them from servers)":
            "Desabilitar {u} e revogar as chaves dele? (o apply remove dos servidores)",
        "Remove {h} from AdminForge? (does not clean keys on the server)":
            "Remover {h} do AdminForge? (nao limpa chaves no servidor)",
        "Revoke {ug} -> {sg}? (apply removes keys)":
            "Revogar {ug} -> {sg}? (o apply remove chaves)",
        "Confirm the fingerprint?": "Confirma o fingerprint?",
        "Apply now?": "Aplicar agora?",
        "captured host_key: {fp}": "host_key capturada: {fp}",
        "User": "Usuario",
        "Credentials ({n})": "Credenciais ({n})",
        "Groups ({n})": "Grupos ({n})",
        "  (none)": "  (nenhum)",
        "Server": "Servidor",
        "Installed keys ({n})": "Chaves instaladas ({n})",
        "User {u}": "Usuario {u}",
        "Effective server access ({n})": "Acesso efetivo a servidores ({n})",
        "  (no servers accessible)": "  (nenhum servidor acessivel)",
        "user is not in any user-group; try: adminforge user-group add-member --group <g> --username {u}":
            "o usuario nao esta em nenhum user-group; tente: adminforge user-group add-member --group <g> --username {u}",
        "(none)": "(nenhum)",
        "Grants from user-group {ug} ({n})": "Concessoes do user-group {ug} ({n})",
        "  (no grants)": "  (nenhuma concessao)",
        "Grants to server-group {sg} ({n})": "Concessoes ao server-group {sg} ({n})",
        "sudo-profile {n}": "sudo-profile {n}",
        "nothing to do — state in sync": "nada a fazer — estado em sincronia",
        "{n} sub-actions across {s} servers": "{n} subacoes em {s} servidores",
        "Diff (authorized_keys)": "Diff (authorized_keys)",
        "    ssh: {e}": "    ssh: {e}",
        "    ssh: could not read authorized_keys (sudo blocked?)":
            "    ssh: nao foi possivel ler authorized_keys (sudo bloqueado?)",
        "  (no installed keys declared)": "  (nenhuma chave instalada declarada)",
        "  ssh failed reading {u}: {e}": "  ssh falhou ao ler {u}: {e}",
        "  ssh: could not read authorized_keys for {u} (sudo blocked?)":
            "  ssh: nao foi possivel ler authorized_keys de {u} (sudo bloqueado?)",
        "  {u} {ref} — declared but not present on server":
            "  {u} {ref} — declarado mas ausente no servidor",
        "  {u} {ref} — declared under {decl} but found under {real}":
            "  {u} {ref} — declarado sob {decl} mas encontrado sob {real}",
        "  {u} {ref} — block on server but not in state":
            "  {u} {ref} — bloco no servidor mas ausente no estado",
        "Summary": "Resumo",
        "matches": "coincidencias",
        "divergences": "divergencias",
        "ssh errors": "erros de ssh",
        "Result": "Resultado",
        "operation": "operacao",
        "status": "status",
        "successes": "sucessos",
        "failures": "falhas",
        "re-running 'adminforge apply' retries only the failed sub-actions":
            "reexecutar 'adminforge apply' retenta apenas as subacoes que falharam",
        "Operation": "Operacao",
        "id": "id",
        "when": "quando",
        "superadmin": "superadmin",
        "command": "comando",
        "hash": "hash",
        "prev_hash": "hash_anterior",
        "Sub-actions ({n})": "Subacoes ({n})",
        "chain intact (last hash: {h})": "cadeia integra (ultimo hash: {h})",
        "State": "Estado",
        "  {users} users, {ugroups} user-groups, {servers} servers, {sgroups} server-groups, {perms} permissions, {sprofiles} sudo-profiles":
            "  {users} usuarios, {ugroups} user-groups, {servers} servidores, {sgroups} server-groups, {perms} permissoes, {sprofiles} sudo-profiles",
        "Pending": "Pendencias",
        "  could not compute delta: {e}": "  nao foi possivel calcular o delta: {e}",
        "  no pending changes — state is in sync with declared":
            "  sem pendencias — o estado esta em sincronia com o declarado",
        "  {n} sub-action(s) across {s} server(s) — run 'adminforge preview' to see, 'adminforge apply' to apply":
            "  {n} subacao(oes) em {s} servidor(es) — rode 'adminforge preview' para ver, 'adminforge apply' para aplicar",
        "Last operation": "Ultima operacao",
        "  (no operations yet)": "  (nenhuma operacao ainda)",
        "by": "por",
        "History chain": "Cadeia do historico",
        "  intact": "  integra",
        "  broken: {e}": "  quebrada: {e}",
        "Empty state. Try: adminforge user add --username <name> --name '<full>' --email <email>":
            "Estado vazio. Tente: adminforge user add --username <nome> --name '<completo>' --email <email>",
        "Users ({n})": "Usuarios ({n})",
        "User groups ({n})": "Grupos de usuarios ({n})",
        "Servers ({n})": "Servidores ({n})",
        "Server groups ({n})": "Grupos de servidores ({n})",
        "Permissions ({n})": "Permissoes ({n})",
        "Sudo profiles ({n})": "Sudo-profiles ({n})",
        "Users ({n}) — humans only (UID >= 1000)":
            "Usuarios ({n}) — so humanos (UID >= 1000)",
        "Groups matching {g} ({n})": "Grupos contendo {g} ({n})",
        "  (no group with explicit members)": "  (nenhum grupo com membros explicitos)",
        "Sudoers — files in /etc/sudoers.d/ ({n})":
            "Sudoers — arquivos em /etc/sudoers.d/ ({n})",
        "  (could not list — ssh has no sudo on the server?)":
            "  (nao foi possivel listar — o ssh nao tem sudo no servidor?)",
        "Active sudo rules ({n})": "Regras de sudo ativas ({n})",
        "  ... +{n} rules (use --format json for full output)":
            "  ... +{n} regras (use --format json para a saida completa)",
        "Running services ({n})": "Servicos em execucao ({n})",
        "Alerts": "Alertas",
        "user {u} exists but no matching service is running":
            "o usuario {u} existe mas nenhum servico correspondente esta rodando",
        "{n} file(s) in /etc/sudoers.d/ outside AdminForge: {files}":
            "{n} arquivo(s) em /etc/sudoers.d/ fora do AdminForge: {files}",

        # kv-keys adicionais (rotulos de campo)
        "username": "usuario",
        "name": "nome",
        "email": "email",
        "hostname": "hostname",
        "ipv4": "ipv4",
        "port": "porta",
        "host_key": "host_key",
        # ---- ui.py ----
        "(empty)": "(vazio)",
        "{cmd}  ({id}) — partial": "{cmd}  ({id}) — parcial",

        # ---- nucleo.py: mensagens de erro ----
        "invalid username: {u}": "username invalido: {u}",
        "name is required": "o nome e obrigatorio",
        "invalid email: {e}": "email invalido: {e}",
        "username {u} already exists": "o username {u} ja existe",
        "key already registered for {u} ({fp})": "chave ja registrada para {u} ({fp})",
        "fingerprint {fp} does not exist": "o fingerprint {fp} nao existe",
        "invalid group name: {n}": "nome de grupo invalido: {n}",
        "group {g} does not exist": "o grupo {g} nao existe",
        "unknown users: {u}": "usuarios desconhecidos: {u}",
        "unknown servers: {s}": "servidores desconhecidos: {s}",
        "invalid hostname: {h}": "hostname invalido: {h}",
        "invalid ipv4: {ip}": "ipv4 invalido: {ip}",
        "invalid port: {p}": "porta invalida: {p}",
        "host_key is required": "a host_key e obrigatoria",
        "server {h} already exists": "o servidor {h} ja existe",
        "--profile only applies when --level is sudo":
            "--profile so se aplica quando --level e sudo",
        "invalid sudo-profile name: {n}": "nome de sudo-profile invalido: {n}",
        "at least one --command is required": "pelo menos um --command e obrigatorio",
        "command must be absolute path: {c} (sudoers requires absolute paths)":
            "o comando precisa ser caminho absoluto: {c} (sudoers exige caminhos absolutos)",
        "command contains forbidden control character: {c}":
            "o comando contem caractere de controle proibido: {c}",
        "sudo-profile {n} already exists": "o sudo-profile {n} ja existe",
        "sudo-profile {n} is in use by {k} permission(s); update or revoke them first":
            "o sudo-profile {n} esta em uso por {k} permissao(oes); atualize ou revogue antes",
        "{kind} {name} has {n} associated permission(s):":
            "{kind} {name} tem {n} permissao(oes) associada(s):",
        "Revoke them first:": "Revogue antes:",
        "permission does not exist": "a permissao nao existe",
        "{u} users, {g} groups, {s} services, {r} sudo rules": "{u} usuarios, {g} grupos, {s} servicos, {r} regras de sudo",
        # rotulos de "kind" usados na mensagem acima
        "user-group": "user-group",
        "server-group": "server-group",
    },
}
