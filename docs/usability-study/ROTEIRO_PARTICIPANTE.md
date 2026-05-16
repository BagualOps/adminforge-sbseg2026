# Roteiro — AdminForge (sessão de uso)

Este é o roteiro que **você** segue durante a sessão. São tarefas baseadas num cenário; **não tem
passo a passo** de propósito — a gente quer ver como *você* faria. Fale em voz alta enquanto trabalha:
o que está pensando, o que está tentando, o que esperava que acontecesse, o que te confundiu. Não
existe resposta "certa" de *como* fazer. Se travar de verdade, pode pedir ajuda; pode parar quando quiser.

---

## Como começar

Você recebeu (por mensagem) **dois arquivos**:

- a **chave SSH privada** que te autentica no servidor (o nome do arquivo está na mensagem);
- **este roteiro**.

Junto, a mensagem também traz três dados específicos da sessão (são esses que você usa nos
comandos abaixo no lugar dos placeholders entre `< >`):

- **`<usuario>@<endereço-do-servidor>`** — onde você vai se conectar;
- **`<fingerprint>`** — o *fingerprint* do servidor (pra confirmar na primeira conexão);
- **`<chave>`** — o nome do arquivo de chave que veio na mensagem.

### 1. Salvar a chave e proteger as permissões

No terminal da **sua máquina** (Linux/Mac, ou Windows 10+ com o `ssh` do PowerShell):

```bash
mkdir -p ~/.ssh
mv <chave> ~/.ssh/
chmod 600 ~/.ssh/<chave>
```

O `chmod 600` é obrigatório — o `ssh` recusa chaves com permissões abertas.

### 2. Conectar

```bash
ssh -i ~/.ssh/<chave> <usuario>@<endereço-do-servidor>
```

**Na primeira conexão**, o `ssh` mostra o *fingerprint* do servidor e pergunta se você confia.
Responda `yes` **somente se** o fingerprint na tela bater **exatamente** com o `<fingerprint>` que
veio na mensagem.

### 3. Já está dentro

Quando você vir um prompt do tipo `<usuario>@<host>:.../lab$`, está tudo pronto:

- a ferramenta **`af`** já está no `PATH` (`adminforge` é o nome longo do mesmo comando);
- **autocomplete** funciona com `Tab` (subcomandos, flags e valores cadastrados);
- o arquivo **`alice.pub`** (vai precisar na Tarefa 1) está no diretório em que você cai — confere com `ls`.

Não precisa instalar nada na sua máquina além do cliente `ssh` (já vem em Linux/Mac, e Windows 10+ tem por padrão no PowerShell). Quando estiver com o prompt aberto, comece quando o facilitador (ou a mensagem) avisar.

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

Rode `af --help`. Em voz alta: na sua leitura, **o que essa ferramenta faz?** Se tivesse que
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

### Tarefa 6 — Dar sudo limitado no banco

A `sre` precisou de **sudo no `banco`** pra resolver um chamado — mas só pra dois comandos
específicos, não sudo geral. O acesso atual da `sre` no `banco` é só `shell` (login sem sudo);
o combinado agora é elevar para **sudo restrito** a estes dois comandos:

- `/bin/journalctl`
- `/bin/systemctl restart postgresql`

**Objetivo:** ajustar o acesso da `sre` ao `banco` de `shell` para **sudo limitado a esses dois
comandos** (não sudo total), e fazer essa mudança valer no servidor.

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

> **Fim das tarefas.** Você "desligou a Alice" num comando só — limpo, auditado, com hash.
> E aí o `audit` do `web-02` revelou uma regra de sudo que ela mesma tinha posto na mão,
> se dando root por fora do AdminForge. Ahhh... *era por isso* que a Alice foi demitida.
> (E é por isso que `apply` sozinho não basta: ele desfaz o que ele fez — o que a Alice
> aprontou por fora, só o `audit` enxerga.)
>
> O facilitador vai te passar um questionário curto e fazer algumas perguntas.
