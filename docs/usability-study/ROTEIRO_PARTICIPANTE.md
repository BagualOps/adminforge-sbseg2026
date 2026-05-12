# Roteiro — AdminForge (sessão de uso)

Este é o roteiro que **você** segue durante a sessão. São tarefas baseadas num cenário; **não tem
passo a passo** de propósito — a gente quer ver como *você* faria. Fale em voz alta enquanto trabalha:
o que está pensando, o que está tentando, o que esperava que acontecesse, o que te confundiu. Não
existe resposta "certa" de *como* fazer. Se travar de verdade, pode pedir ajuda; pode parar quando quiser.

---

## Como começar

O facilitador vai te dizer como **entrar** no ambiente (um `ssh ...` ou comando equivalente que cai
num terminal já com a ferramenta `adminforge` disponível — tem **autocomplete** com `Tab`, e `af`
funciona como atalho de `adminforge`).

A **chave pública da Alice** (Tarefa 1) está num arquivo `alice.pub` no diretório em que você cai —
um `ls` mostra. Quando estiver no terminal, comece quando o facilitador disser.

---

## Cenário

Você entrou esta semana como pessoa **SRE / administradora de sistemas** numa empresa. A frota é
pequena — três servidores Linux:

- **`web-01`** e **`web-02`** — servidores de aplicação;
- **`db-03`** — banco de dados.

A empresa controla *quem tem acesso SSH e sudo* a esses servidores com uma ferramenta de linha de
comando chamada **AdminForge**, que você vai operar a partir deste terminal. Uma coisa importante: o
que você muda na ferramenta só vai de fato para os servidores quando você mandar — faz parte do
trabalho descobrir como.

---

### Tarefa 0 — Primeira impressão (aquecimento)

Rode `adminforge --help`. Em voz alta: na sua leitura, **o que essa ferramenta faz?** Se tivesse que
começar do zero, **por onde começaria?**

*(Não precisa "concluir" nada aqui — é só pra calibrar e ouvir sua primeira impressão.)*

---

### Tarefa 1 — Cadastrar uma colega e a chave dela

Sua colega **Alice** vai precisar de acesso. Dados: nome "Alice Souza", e-mail `alice@empresa.com`,
login Unix `alice`. A chave pública SSH dela está no arquivo **`alice.pub`** (no diretório em que você está; `ls` mostra).

**Objetivo:** a Alice cadastrada no AdminForge, com a chave pública dela registrada.

> Avise quando achar que terminou.

---

### Tarefa 2 — Colocar a frota no AdminForge

Os três servidores ainda não estão cadastrados no AdminForge. A frota:

| Servidor | Endereço | Porta SSH |
|----------|----------|-----------|
| `web-01` | `127.0.0.1` | `2201` |
| `web-02` | `127.0.0.1` | `2202` |
| `db-03`  | `127.0.0.1` | `2203` |

**Objetivo:** os três servidores cadastrados no AdminForge.

---

### Tarefa 3 — Organizar em grupos

A empresa trabalha com grupos:

- um grupo de **usuários** chamado **`sre`**, do qual a Alice faz parte;
- um grupo de **servidores** chamado **`app`**, com `web-01` e `web-02`;
- um grupo de **servidores** chamado **`banco`**, só com `db-03`.

**Objetivo:** esses três grupos criados, com os membros indicados.

---

### Tarefa 4 — Conceder os acessos

A política é:

- a equipe **`sre`** tem acesso **`sudo`** aos servidores de **aplicação** (`app`);
- a equipe **`sre`** tem acesso só de **`shell`** (login sem sudo) ao **`banco`**.

**Objetivo:** essas duas concessões registradas no AdminForge.

---

### Tarefa 5 — Fazer valer e conferir

Até agora você mexeu na ferramenta, mas os servidores ainda não sabem de nada disso.

**Objetivo:** fazer o que for preciso para que essas mudanças cheguem **de fato** aos três servidores,
e depois **confirmar** que ficou como deveria.

---

### Tarefa 6 — Restringir o sudo no banco

Mudança de planejamento: no **`db-03`**, ninguém da `sre` deveria ter sudo *total*. O combinado agora
é que a `sre`, no `banco`, possa rodar **com sudo apenas estes dois comandos**:

- `/bin/journalctl`
- `/bin/systemctl restart postgresql`

**Objetivo:** ajustar o acesso da `sre` ao `banco` para sudo **limitado a esses dois comandos**, e
fazer essa mudança valer no servidor.

---

### Tarefa 7 — Alguém saiu da empresa

A **Alice** saiu da empresa hoje.

**Objetivo:** remover o acesso dela de **toda a frota** e fazer isso valer nos servidores.

---

### Tarefa 8 — Investigar um servidor *(se houver tempo)*

Chegou um aviso de que talvez alguém tenha criado **uma regra de sudo na mão**, fora do AdminForge,
no **`web-02`**.

**Objetivo:** verificar isso e me dizer **o que você encontrou** — há algo no `web-02` fora do
controle do AdminForge?

---

### Tarefa 9 — O que foi feito hoje *(se houver tempo)*

**Objetivo:** mostrar o **histórico** das operações desta sessão e confirmar que esse registro
**não foi adulterado**.

---

> Fim das tarefas. O facilitador vai te passar um questionário curto e fazer algumas perguntas.
