# Guia do facilitador — estudo de usabilidade do AdminForge

Companion do [`ROTEIRO_PARTICIPANTE.md`](ROTEIRO_PARTICIPANTE.md). **Não mostrar ao participante.**
Aqui ficam: pré-condições do lab, script de abertura, política de intervenção, os critérios de
sucesso e dicas por tarefa, e o fechamento (rubrica de Whitten & Tygar, SUS,
TAM, entrevista). Para a escolha do método, ver [`METODOLOGIA-OPCOES.md`](METODOLOGIA-OPCOES.md)
(estamos na **Opção 1 — estudo moderado de laboratório**). O ambiente está em [`lab/`](lab/).

---

## 1. Pré-condições (preparar antes da sessão)

- **Lab no ar** (`lab/prep.sh` na máquina-host): o participante entra via `ssh`, dá `source` no
  `env.sh` (que o leva pra pasta do lab) e tem o comando `adminforge` disponível (com **autocomplete**
  via argcomplete), `ADMINFORGE_STATE` num diretório **vazio**, a chave de serviço em
  `keys/adminforge_id` e o arquivo **`alice.pub`** (chave pública de exemplo da "Alice") na pasta do
  lab — o diretório onde ele cai. Os três alvos `web-01`, `web-02`, `db-03` são containers com o
  usuário de serviço + a pubkey do AdminForge já instalados.
- **IPs/portas da frota** já estão na **Tarefa 2 do roteiro do participante** (`web-01 → 127.0.0.1:2201`,
  `web-02 → :2202`, `db-03 → :2203`) — você não precisa relatar nada de viva voz. Só confirme que batem
  com a saída do `prep.sh`; se o seu lab usa portas diferentes, ajuste a tabela da Tarefa 2 antes da sessão.
- **Drift semeado:** no `web-02`, o lab já criou um `/etc/sudoers.d/zzz-alice` — uma regra de sudo
  da própria Alice (`alice ALL=(ALL) NOPASSWD:ALL`), feita na mão, fora do AdminForge. É o que o
  participante deve achar na Tarefa 8; e o *gancho* da piada no fim do roteiro (a Alice foi demitida
  justamente por ter se dado root por fora). Sobrevive ao offboarding da T7 — não é um arquivo `adminforge-*`.
- O participante **não** recebe `USAGE.md` / `QUICKSTART.md` / `ROTEIRO.md` da ferramenta. Pode usar
  `adminforge --help` / `-h` à vontade em qualquer subcomando, e o `Tab`.
- Gravação de tela ligada (compartilhamento de tela na call, ou `script`/`asciinema` no shell — o
  `lab/reset.sh` arquiva o `~/.bash_history`).
- Folha de observação impressa/aberta (modelo na seção 5).

## 2. Script de abertura (falar com o participante)

- Agradecer; explicar em 2 frases o objetivo ("entender como uma pessoa que administra servidores
  Linux se vira com essa ferramenta sem ter lido a documentação — não é você que está sendo avaliado,
  é a ferramenta").
- Consentimento: gravação de tela e áudio, pseudonimização (você será "P*n*"), pode parar a qualquer
  momento sem justificativa, dados guardados em local restrito. Coletar assinatura (formulário à parte).
- Pré-questionário de perfil (formulário à parte): cargo, anos administrando Linux, com que ferramentas
  gerencia acesso hoje, familiaridade com CLI.
- Explicar o *think-aloud*: "narre o que está pensando e fazendo, em voz alta, o tempo todo. Se ficar
  em silêncio eu vou te lembrar." Fazer 30s de aquecimento de think-aloud se a pessoa não conhece
  (ex.: "me diga em voz alta como você abriria um arquivo no seu editor").
- Entregar o `ROTEIRO_PARTICIPANTE.md` (esse arquivo já é só do participante). "Comece pela Tarefa 0."

## 3. Política de intervenção

- Deixe a pessoa tentar e narrar. **Só intervenha** se ela (a) ficar visivelmente travada > ~2 min
  sem nova hipótese, (b) pedir ajuda, ou (c) estiver prestes a sair do escopo da tarefa.
- Escala de dica — registre o nível usado:
  - **Nível 1 (reorienta, não entrega):** ex. "o que você quer é gerenciar *permissão* — já olhou o
    que tem por aí relacionado a isso?"
  - **Nível 2 (aponta o caminho):** ex. "dá uma olhada em `adminforge permission --help`."
  - **Mostrar:** você executa/explica; marque a tarefa como **falha (assistida)**.
- Não corrija erros silenciosamente. Se a pessoa fez algo errado e seguiu adiante achando que estava
  certo, **deixe** — anote, e veja se ela descobre sozinha numa tarefa posterior (várias tarefas têm
  um ponto natural de descoberta — `permission list`, `preview`, `audit server`).
- Perguntas do participante: devolva ("o que você acha que faz?", "o que você esperaria?") antes de
  responder; só responda direto se for sobre o cenário/ambiente, não sobre a ferramenta.

## 4. Métricas por tarefa (o que registrar)

Para cada tarefa: **resultado** (`sucesso s/ ajuda` / `sucesso c/ ajuda` / `falha`), **tempo**,
**nº de `--help`/`-h`**, **nº de comandos com erro** (rc≠0 antes do que deu certo), **nº de consultas
a doc** (não deveria precisar), **erro perigoso** (sim/não + descrição verbatim do que a pessoa disse).

**Erro perigoso** = executou (ou estava a um Enter de executar) ação destrutiva/insegura **achando que
estava certa**. É o achado mais importante do estudo. A lista por tarefa está na seção 6.

---

## 5. Folha de observação (modelo)

```
Participante: P__    Data: ____/____/____    Versão AdminForge (commit): ____________
Perfil (resumo): _________________________________________________________________

Tarefa | Resultado          | Tempo | #help | #erros | #doc | Erro perigoso? | Notas
-------+--------------------+-------+-------+--------+------+----------------+---------------------------
  0    | (aquecimento)      |   —   |   —   |   —    |  —   |       —        |
  1    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  2    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  3    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  4    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  5    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  6    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  7    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  8    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |
  9    | s/ajuda c/ajuda fa |       |       |        |      |   não / sim:   |

Episódios de dificuldade (onde travou / o que disse / o que tentou):
- ...

Rubrica Whitten & Tygar (sim / parcial / não + 1 frase de evidência):
  (1) percebeu de forma confiável as tarefas de segurança a fazer?  ____  — 
  (2) descobriu como executá-las?                                   ____  — 
  (3) NÃO cometeu erro perigoso?                                    ____  — 
  (4) ficou confortável o bastante pra continuar usando?            ____  — 

SUS (escore 0–100): ____    TAM (PU/PEOU/Intenção, médias): ___ / ___ / ___
Citações marcantes da entrevista:
- ...
```

---

## 6. Critérios, dicas e o que observar (por tarefa)

> Comandos de verificação assumem o lab padrão: `adminforge` no PATH do participante, alvos em
> `127.0.0.1:2201/2202/2203`, containers `adminforge-lab-web-01` / `-web-02` / `-db-03`.

### Tarefa 0 — Primeira impressão
- **Critério:** não há (aquecimento). Não cronometrar pra efetividade.
- **Observar:** *mental model* inicial — entende que é "gerenciar acesso/sudo numa frota"? Percebe que
  há um passo de "aplicar"? O que diz que faria primeiro bate com o fluxo (cadastrar user/server →
  grupo → permissão → apply)? Anote a frase de primeira impressão.

### Tarefa 1 — Cadastrar a Alice + chave
- **Sucesso:** existe o usuário `alice` com ≥ 1 chave registrada.
- **Verificar:** `adminforge user show --username alice` (dados + chave) — ou `... --format json`.
- **Tempo-alvo:** ~3 min.
- **Dicas:** (1) "Você quer a pessoa cadastrada *e* a chave dela. Viu `adminforge user --help` e
  `adminforge user add --help`?" (2) "`adminforge user add --username ... --name ... --email ... --key-file alice.pub`
  faz as duas coisas; ou em dois passos: `user add` e depois `user key add --file alice.pub`."
- **Observar:** acha `user add`? Descobre que a chave é subcomando à parte (`user key add`) e que dá
  pra apontar arquivo? Erra login × nome × e-mail? Lê a mensagem de erro quando erra?
- **Erro perigoso:** ~nenhum (reversível, sem efeito em servidor).

### Tarefa 2 — Cadastrar os 3 servidores (TOFU)
- **Sucesso:** `web-01`, `web-02`, `db-03` na lista de servidores.
- **Verificar:** `adminforge server list` (3 linhas) — ou `... --format json`.
- **Tempo-alvo:** ~6 min (mais atrito por causa do *host key*).
- **Dicas:** (1) "Como cadastraria um servidor que nunca conectou antes? Olha `adminforge server add
  --help` — tem um jeito 'automático'." (2) "`adminforge server add --hostname web-01 --ip 127.0.0.1
  --port 2201 --auto`; repita pros outros (2202, 2203)."
- **Observar (PP2):** ao aparecer `host_key capturada: SHA256:...  Confirma o fingerprint? [y/N]` — a
  pessoa só digita `y`, ou pausa/comenta que deveria validar por outro canal? Anote verbatim. Descobre
  `--auto`? Usa `--port`? Se perde tentando colar host key na mão?
- **Erro perigoso:** aceitar o *host key* sem hesitação **e** sem perceber que é o "T" do TOFU
  (perigoso em potencial — sem MITM no lab, mas registre).

### Tarefa 3 — Grupos
- **Sucesso:** user-group `sre` ⊇ {`alice`}; server-group `app` ⊇ {`web-01`,`web-02`}; server-group
  `banco` ⊇ {`db-03`}.
- **Verificar:** `adminforge dump --format json` (ou `user-group list` / `server-group list` /
  `user-group show --name sre` se houver).
- **Tempo-alvo:** ~5 min.
- **Dicas:** (1) "Há comandos separados pra grupo de *usuários* e de *servidores* — `adminforge --help`
  lista os menus." (2) "`adminforge user-group create --name sre` + `... add-member --group sre
  --username alice`; análogo com `server-group`."
- **Observar:** distingue user-group × server-group? Descobre que `add-member` aceita vários de uma vez?
  Tenta `create` já com membros? `--name` (create) × `--group` (add-member) confunde?
- **Erro perigoso:** ~nenhum.

### Tarefa 4 — Conceder acessos
- **Sucesso:** exatamente duas permissões — `sre → app : sudo` e `sre → banco : shell`.
- **Verificar:** `adminforge permission list` (ou `... --format json`); confira nível e pares.
- **Tempo-alvo:** ~5 min.
- **Dicas:** (1) "Tudo que é *conceder/revogar/listar* permissão fica num menu só — qual?" (2)
  "`adminforge permission grant --user-group sre --server-group app --level sudo` e `... --server-group
  banco --level shell`."
- **Observar (PP4):** a pessoa procura um `grant` no topo (não existe — foi consolidado em `permission`)
  e leva quanto pra achar `permission grant`? O `adminforge permission --help` deixa óbvio? Entende a
  direção (user-group **para** server-group)? Confunde `shell` × `sudo`?
- **Erro perigoso:** conceder `sudo` onde era `shell` (ou grupo/server errado) **e seguir achando que
  está certo**. Não corrija — veja se descobre na Tarefa 5.

### Tarefa 5 — Aplicar e verificar
- **Sucesso:** rodou `adminforge apply` com status `SUCESSO`; **e** confirmou de algum jeito —
  idealmente `adminforge apply verify` sem *drift*, ou `adminforge audit server --hostname web-01`
  mostrando a Alice com sudo. Bônus (não obrigatório): usou `adminforge preview` **antes** do apply.
- **Verificar:** saída do `apply` — 5 subações (`app`: 2 servidores × {chave, sudoers}; `banco`: 1
  servidor × {chave}), todas `sucesso`; depois `adminforge apply verify` (rc 0). No servidor: `docker
  exec adminforge-lab-web-01 sudo cat /home/alice/.ssh/authorized_keys` (bloco `BEGIN adminforge: alice:`);
  `docker exec adminforge-lab-web-01 sudo cat /etc/sudoers.d/adminforge-alice` (`alice ALL=(ALL) NOPASSWD:ALL`).
- **Tempo-alvo:** ~5 min.
- **Dicas:** (1) "Como as mudanças saem da ferramenta e vão pros servidores? E como você vê o que vai
  acontecer *antes*?" (2) "`adminforge preview` mostra o delta; `adminforge apply` aplica; `adminforge
  apply verify` compara declarado vs. real."
- **Observar (PP4):** entende sozinha que há um `apply` separado? Procura com que nome (`apply`, `sync`,
  `deploy`, `push`)? Usa `preview` antes? Ao "confirmar", confia só no `apply` ou vai além? Se errou na
  Tarefa 4, percebe agora?
- **Erro perigoso:** aplicar sem olhar o delta e propagar a concessão errada da Tarefa 4.

### Tarefa 6 — Sudo restrito (sudo-profile)
- **Sucesso:** existe um *sudo-profile* com exatamente `/bin/journalctl` e `/bin/systemctl restart
  postgresql`; a permissão `sre → banco` agora é `sudo` **com esse profile** (não mais `shell`, nem
  `sudo` total); aplicado — no `db-03`, o sudoers da Alice tem só essas duas linhas.
- **Verificar:** `adminforge sudo-profile show --name <nome>`; `adminforge permission show --server-group
  banco` (nível `sudo` + nome do profile); após o apply: `docker exec adminforge-lab-db-03 sudo cat
  /etc/sudoers.d/adminforge-alice` → `alice ALL=(ALL) NOPASSWD: /bin/journalctl` e `... NOPASSWD:
  /bin/systemctl restart postgresql`, **sem** `NOPASSWD:ALL`; `docker exec adminforge-lab-db-03 sudo
  visudo -c` → ok.
- **Tempo-alvo:** ~7 min (composta).
- **Dicas:** (1) "Existe um conceito de 'perfil de sudo' — conjunto nomeado de comandos permitidos.
  Procure por isso; depois ligue o perfil na concessão." (2) "`adminforge sudo-profile create --name
  db-ops --command /bin/journalctl --command '/bin/systemctl restart postgresql'`; depois `adminforge
  permission grant --user-group sre --server-group banco --level sudo --profile db-ops` (isso *atualiza*
  a permissão existente); por fim `adminforge apply`."
- **Observar:** descobre `sudo-profile`? Entende que `permission grant` repetido *atualiza* (não
  duplica)? Sabe que precisa de caminho **absoluto** (a ferramenta rejeita relativo — lê o erro)?
  Lembra do `apply`? Faz `preview` antes?
- **Erro perigoso:** deixar a `sre` com `sudo` **total** no `db-03` (ex.: `permission grant ... --level
  sudo` **sem** `--profile`) **achando que aplicou a restrição**. Caça-erro principal desta tarefa.

### Tarefa 7 — Alice saiu
- **Sucesso:** a Alice sem acesso a nenhum servidor após o `apply` — `authorized_keys` sem o bloco do
  AdminForge em todos, e sem `sudoers.d/adminforge-alice`.
- **Verificar:** `adminforge user show --username alice` (status `inativo`, credenciais `revogada`);
  `adminforge preview` antes do apply mostra `remover_chave alice ...` onde ela tinha; após o apply:
  `docker exec adminforge-lab-web-01 sudo cat /home/alice/.ssh/authorized_keys` → sem `BEGIN adminforge:
  alice:`; `docker exec adminforge-lab-web-01 ls /etc/sudoers.d/adminforge-alice` → não existe;
  `adminforge audit server --hostname web-01` → não lista a Alice (ou só a conta Unix sem chave do AdminForge).
- **Tempo-alvo:** ~5 min.
- **Dicas:** (1) "'Saiu da empresa' — qual ação: tirar do grupo, desabilitar, apagar? O que cada uma
  faz? E o que falta pra valer nos servidores?" (2) "`adminforge user disable --username alice` revoga
  as chaves dela; depois `adminforge apply`."
- **Observar (PP4):** escolhe `user disable` (revoga em todo lugar) × `user-group remove-member` (só
  tira do grupo) × tenta `delete`? Entende a diferença? Lembra do `apply`? Usa `preview` pra conferir
  o escopo?
- **Erro perigoso:** achar que `remove-member` (ou revogar uma chave só) "demitiu" a Alice quando ela
  ainda tem acesso por outro caminho; ou esquecer o `apply` e ir embora achando que o acesso já caiu.

### Tarefa 8 — Investigar o `web-02` *(opcional)*
- **Sucesso:** roda `adminforge audit server --hostname web-02`, lê a saída e **reporta** que há um
  arquivo em `/etc/sudoers.d/` **não gerenciado pelo AdminForge** (o `zzz-alice` — `alice ALL=(ALL)
  NOPASSWD:ALL`), citando-o como *drift*/risco. Ponto de ensino: a Alice foi "offboarded" na T7, mas
  essa regra manual sobreviveu — o `apply` desfaz só o que o AdminForge instalou.
- **Verificar:** a seção **Alerts** do `audit server` sinaliza arquivos fora do AdminForge — confira se
  a pessoa percebeu *ali*, não só passou o olho.
- **Tempo-alvo:** ~4 min.
- **Dicas:** (1) "A ferramenta sabe inspecionar um servidor por dentro — usuários, grupos, sudoers,
  serviços. Procura algo de 'auditar'." (2) "`adminforge audit server --hostname web-02`; olhe a seção
  *Alerts* e a lista de `sudoers.d/`."
- **Observar:** acha `audit server`? Lê a seção *Alerts* ou ignora? Distingue `adminforge-*` de manual?
  Sabe dizer o que faria a respeito?
- **Erro perigoso:** declarar "tá tudo certo" sem ter visto o arquivo manual (falso negativo de auditoria).

### Tarefa 9 — Histórico e integridade *(opcional)*
- **Sucesso:** roda `adminforge history list` (vê as operações da sessão) **e** `adminforge history
  verify` (cadeia SHA-256 íntegra → ok).
- **Verificar:** observar; `history verify` deve dizer que a cadeia está consistente.
- **Tempo-alvo:** ~3 min.
- **Dicas:** (1) "Tem um menu de histórico — e nele um jeito de checar adulteração." (2) "`adminforge
  history list` e `adminforge history verify`."
- **Observar:** acha o menu `history`? Entende o que `verify` faz (e por que importa numa ferramenta de
  segurança)? Tenta `history show --id ...`?
- **Erro perigoso:** ~nenhum (read-only).

---

## 7. Fechamento da sessão

1. **Rubrica de Whitten & Tygar** — preencher na folha de observação as 4 propriedades (`sim`/`parcial`/
   `não` + 1 frase de evidência): a pessoa (1) percebeu de forma confiável as tarefas de segurança que
   precisava fazer; (2) descobriu como executá-las; (3) **não cometeu erro perigoso**; (4) ficou
   confortável o bastante pra continuar usando.
2. **Questionário pós-teste** (formulário à parte): **SUS** (10 itens) + **TAM** (Utilidade Percebida,
   Facilidade de Uso Percebida, Intenção de Uso).
3. **Entrevista semiestruturada (5–10 min)** — registrar respostas/citações:
   - Qual foi o **pior** momento da sessão? E o **melhor**?
   - O que você **mudaria** na ferramenta?
   - Você **usaria** isso no seu trabalho? Por quê / por que não?
   - Comparado ao jeito que você faz **isso hoje**, é melhor ou pior — em quê?
   - Em algum momento você achou que tinha feito uma coisa e tinha feito outra? Onde?
4. **Encerramento** — agradecer; incentivo se houver.
5. **`lab/reset.sh`** antes do próximo participante (zera o estado, recria o `alice.pub` na pasta do
   lab, recria os containers, arquiva o histórico da sessão).
