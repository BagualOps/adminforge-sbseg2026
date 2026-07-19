# Questionário - estudo de usabilidade do AdminForge

Companion do [`GUIA_FACILITADOR.md`](GUIA_FACILITADOR.md) e do [`ROTEIRO_PARTICIPANTE.md`](ROTEIRO_PARTICIPANTE.md).
Reúne os **formulários à parte** citados no guia do facilitador: o pré-questionário de perfil
(seção 2), as fichas pós-tarefa, o questionário pós-teste e o roteiro de entrevista (seção 7).
Estamos na **Opção 1** de [`METODOLOGIA-OPCOES.md`](METODOLOGIA-OPCOES.md) - estudo moderado de
laboratório.

Os instrumentos seguem as referências da pasta [`referencias/`](referencias/README.md): **TAM**
`[Davis89]` (Utilidade Percebida, Facilidade de Uso Percebida, Intenção de Uso) e a rubrica das
4 propriedades de Whitten & Tygar `[W&T99]`.

> **Sobre a escolha dos instrumentos - honestidade metodológica.** A `METODOLOGIA-OPCOES.md`
> previa **SUS + TAM** como questionário pós-teste da Opção 1; o **SUS foi removido** - o
> pós-teste usa só o **TAM**. Vale registrar que os três estudos-análogos de laboratório com
> profissionais - Krombholz `[Krombholz17]`, Tiefenau `[Tiefenau19]` e Smith `[Smith20]` -
> **não usaram TAM nem SUS**: cada um montou um questionário próprio (Likert de dificuldade por
> tarefa, autoavaliação "concluiu? sim/não/não sei" e perguntas abertas). Por isso a **Parte B**
> (ficha pós-tarefa) deste documento existe - ela incorpora o que aqueles estudos validaram no
> nosso exato contexto e complementa o TAM.

**Como administrar - resumo:**

| Parte | Quando | Quem preenche |
|-------|--------|---------------|
| Consentimento | No início, antes de tudo | Participante |
| A - Perfil | Antes da Tarefa 0, logo após o consentimento | Participante |
| B - Pós-tarefa | Logo após cada tarefa concluída (Tarefas 1–9) | Participante |
| C - Pós-teste (TAM) | Depois da Tarefa 9, **antes** do debrief/entrevista | Participante |
| D - Entrevista | Depois da Parte C | Facilitador conduz |
| E - Pontuação | Após a sessão | Facilitador |

> **Por que essa ordem.** O TAM deve ser respondido *depois de usar* a ferramenta e *antes* de
> qualquer discussão ou debrief - a entrevista da Parte D enviesaria as respostas. Peça resposta
> **imediata**, sem ruminar item a item.

> **Versão da ferramenta.** Registre **uma vez por rodada do estudo** o commit do AdminForge
> testado (`git rev-parse --short HEAD`) - os resultados só são comparáveis dentro da mesma versão.

> **Versão Google Forms.** Dois scripts geram os formulários do participante:
> [`criar-formulario-consentimento.gs`](criar-formulario-consentimento.gs) gera o termo de
> consentimento (formulário à parte - ver abaixo); [`criar-formulario-google.gs`](criar-formulario-google.gs)
> gera as Partes A, B e C como **um único Google Form** (A no início, 9 seções de tarefa durante a
> sessão, C no fim - 1 envio por participante, identificado só pelo ID). As Partes D e E ficam
> fora: D é entrevista ao vivo, E é a pontuação do facilitador.

---

## Termo de consentimento

> É um **formulário Google à parte** (gerado por
> [`criar-formulario-consentimento.gs`](criar-formulario-consentimento.gs)), aplicado **antes** da
> Parte A. O participante lê o termo, marca "Li e concordo" (campo **obrigatório**) e informa
> **nome completo**, **ID** e **data**. É **consentimento documentado digital**: registra o aceite,
> mas não é assinatura de próprio punho - se a ética/banca exigir assinatura, mantenha também a
> versão em papel.
>
> **Por que um formulário separado.** O nome do participante fica **só neste formulário** - nunca
> na mesma planilha que as respostas do questionário (que é identificado apenas pelo ID `Pn`). É
> assim que a pseudonimização prometida no termo se sustenta - e é o que Krombholz e Tiefenau fazem.

**Termo de Consentimento Livre e Esclarecido**

- **O estudo.** Você vai realizar tarefas com a ferramenta AdminForge, narrando seu raciocínio em voz alta, e responder a questionários curtos - cerca de 1 hora. Quem está sendo avaliado é a ferramenta, não você.
- **Gravação.** A sessão terá gravação de tela e de áudio (não de vídeo da sua imagem).
- **Confidencialidade.** Você será identificado(a) apenas por um pseudônimo (ex.: "P3"); seu nome fica só neste formulário, separado das respostas, e não aparece nos dados analisados nem em publicações.
- **Participação voluntária.** Você pode interromper a qualquer momento, sem justificar e sem nenhum prejuízo.

```
( ) Li o termo acima, tive minhas dúvidas esclarecidas e concordo em participar
    voluntariamente deste estudo.   (obrigatório)

Nome completo: ____________________   Participante (ID): ______   Data: ____/____/____
```

---

## Parte A - Pré-questionário de perfil

> Preencher antes da Tarefa 0. Serve para caracterizar a amostra e checar a triagem (queremos
> quem **não** conhece o AdminForge). Não há resposta certa.

```
Participante: P____        Data: ____/____/____
```

**A1.** Cargo / função atual: ______________________________________________

**A2.** Há quanto tempo você administra servidores Linux profissionalmente?
- ( ) menos de 1 ano
- ( ) 1 a 3 anos
- ( ) 3 a 7 anos
- ( ) mais de 7 anos

**A3.** Qual o tamanho aproximado da frota de servidores que você administra hoje?
- ( ) não administro uma frota   ( ) 1–10   ( ) 11–50   ( ) 51–200   ( ) mais de 200

**A4.** Como você gerencia acesso SSH e `sudo` hoje? *(marque todas que se aplicam)*
- ( ) manualmente, servidor a servidor (editar `authorized_keys` / `sudoers` à mão)
- ( ) Ansible / Puppet / Chef / Salt ou similar
- ( ) FreeIPA / LDAP / Active Directory / Kerberos
- ( ) scripts próprios
- ( ) outra: ______________________________________________

**A5.** Avalie sua familiaridade com cada item *(1 = nenhuma … 5 = muita)*:

| | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Linha de comando / terminal Linux | ( ) | ( ) | ( ) | ( ) | ( ) |
| Chaves SSH e *fingerprints* de host | ( ) | ( ) | ( ) | ( ) | ( ) |
| Configuração de `sudo` / `sudoers` | ( ) | ( ) | ( ) | ( ) | ( ) |
| Ferramentas declarativas / *infra as code* | ( ) | ( ) | ( ) | ( ) | ( ) |
| Conceitos de segurança operacional (hardening, privilégio mínimo, auditoria) | ( ) | ( ) | ( ) | ( ) | ( ) |

**A6.** Você já conhecia ou usou o AdminForge antes desta sessão?
- ( ) nunca ouvi falar   ( ) já ouvi falar, nunca usei   ( ) já usei

> Se A6 = "já usei", registre na folha de observação - o participante não é elegível como
> "novato" e o caso deve ser analisado à parte.

---

## Parte B - Ficha pós-tarefa

> Uma ficha curtíssima, aplicada **logo após cada tarefa** das 1 a 9 (a Tarefa 0 é aquecimento -
> não tem ficha). Leva ~20 s. Não comente a resposta com o participante; só recolha.
>
> **De onde vem.** Krombholz `[Krombholz17]` perguntou, no questionário de saída, *"Did you
> successfully complete the TLS configuration task? (Yes / No / Not sure)"* - e 18 de 28
> participantes responderam que tinham concluído, vários **errado**. Tiefenau `[Tiefenau19]`
> aplicou um Likert de dificuldade **por subtarefa** logo após cada uma. A Parte B funde os dois:
> em vez de uma autoavaliação única no fim, mede confiança (B1) e dificuldade percebida (B2) a
> cada uma das 9 tarefas - granularidade que o TAM não captura.
>
> A combinação **B1 alto + tarefa de fato falhada** é o sinal central do estudo: a pessoa
> *acha* que acertou e não acertou - o "erro perigoso cometido com confiança" `[W&T99]`. Por isso
> a ficha pós-tarefa pergunta confiança **antes** de o participante saber o resultado.

```
Participante: P____    Tarefa nº: ____
```

**B1.** Quão confiante você está de que concluiu esta tarefa **corretamente**?

```
Nada confiante   1  --  2  --  3  --  4  --  5  --  6  --  7   Totalmente confiante
```

**B2.** No geral, realizar esta tarefa foi: *(Single Ease Question)*

```
Muito difícil    1  --  2  --  3  --  4  --  5  --  6  --  7   Muito fácil
```

**B3.** *(opcional, uma frase)* O que mais te atrapalhou ou te deu segurança nesta tarefa?
______________________________________________________________________

---

## Parte C - Questionário pós-teste

> Aplicar **uma vez**, depois da Tarefa 9 e **antes** da entrevista. Peça ao participante que
> marque a **primeira reação** a cada frase, sem pensar demais. Todas as frases devem ser
> respondidas; se não souber responder uma, marque o ponto central da escala.

```
Participante: P____        Data: ____/____/____
```

### C.1 - TAM (Technology Acceptance Model)

`[Davis89]` - escala de 7 pontos. Mede três construtos: **Utilidade Percebida (PU)**,
**Facilidade de Uso Percebida (PEOU)** e **Intenção de Uso (ITU)**. Os itens abaixo são
**adaptados** ao contexto do AdminForge (não verbatim) - prática padrão do TAM, que substitui o
nome do sistema e o domínio de tarefa nas frases originais de Davis.

```
            Discordo                                       Concordo
          totalmente                                     totalmente
              1        2        3        4        5        6        7
```

**Utilidade Percebida (PU)**

| # | Afirmação | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|-----------|---|---|---|---|---|---|---|
| PU1 | Usar o AdminForge me permitiria realizar tarefas de gestão de acesso mais rapidamente. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| PU2 | Usar o AdminForge melhoraria meu desempenho na administração de acesso da frota. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| PU3 | Usar o AdminForge reduziria a chance de eu cometer um erro de acesso ou de `sudo`. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| PU4 | De forma geral, eu consideraria o AdminForge útil no meu trabalho. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |

**Facilidade de Uso Percebida (PEOU)**

| # | Afirmação | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|-----------|---|---|---|---|---|---|---|
| PE1 | Aprender a operar o AdminForge foi fácil para mim. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| PE2 | Achei fácil fazer o AdminForge fazer o que eu queria. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| PE3 | Minha interação com o AdminForge foi clara e compreensível. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| PE4 | De forma geral, achei o AdminForge fácil de usar. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |

**Intenção de Uso (ITU)**

| # | Afirmação | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|-----------|---|---|---|---|---|---|---|
| IT1 | Se o AdminForge estivesse disponível no meu trabalho, eu pretenderia usá-lo para gerenciar acesso. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| IT2 | Eu preferiria usar o AdminForge ao jeito como faço a gestão de acesso hoje. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| IT3 | Eu recomendaria o AdminForge a um colega que administra uma frota Linux. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |

### C.2 - Confiança e segurança percebida *(itens complementares - opcional)*

> Itens **próprios**, não validados, fora do TAM - **não entram no escore** dele.
> Servem para quantificar as 4 propriedades de Whitten & Tygar `[W&T99]` (a pessoa foi informada
> das tarefas de segurança, conseguiu executá-las com sucesso, não cometeu erro perigoso, ficou
> confortável com a interface) e a pergunta-chave do estudo: a ferramenta protege contra o **erro
> perigoso**? Use-os ou descarte-os conforme o tempo da sessão. Escala de 7 pontos, mesma régua do TAM.
>
> O item **SC2** ("deixou claro o que cada ação faria") espelha a dimensão *Transparent* do
> diferencial semântico de Tiefenau `[Tiefenau19]`: lá, a ferramenta automatizada (Certbot) teve
> a **pior nota justamente em transparência** - os participantes não sabiam o que ela tinha feito
> por baixo. Para o AdminForge, em que `preview`/`apply` decidem o que vai para os servidores,
> essa é uma dimensão crítica.

| # | Afirmação | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|-----------|---|---|---|---|---|---|---|
| SC1 | Confio que os acessos da frota ficaram exatamente como eu pretendia. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| SC2 | A ferramenta deixou claro, **antes de eu confirmar**, o que cada ação faria nos servidores. | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |
| SC3 | Senti que a ferramenta me protegeria de cometer um erro perigoso (ex.: dar `sudo` ao grupo ou servidor errado). | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) | ( ) |

---

## Parte D - Roteiro de entrevista semiestruturada (5–10 min)

> Conduzida pelo facilitador, **depois** da Parte C. Pergunta aberta; deixe a pessoa falar e
> registre citações verbatim. As perguntas são as da seção 7.3 do `GUIA_FACILITADOR.md`,
> consolidadas aqui. Seguem o formato das perguntas pós-estudo de Smith `[Smith20]` (Apêndice C:
> *"Which functionalities did you like most / dislike most? … Were there moments when you were
> confused? … Would you use this tool in your work?"*) e das reflexões de saída de Krombholz
> `[Krombholz17]` (*"What did you find particularly difficult? … What would you recommend?"*).

1. Qual foi o **pior** momento da sessão? E o **melhor**?
2. O que você **mudaria** na ferramenta, se pudesse mudar uma coisa?
3. Você **usaria** o AdminForge no seu trabalho? Por quê / por que não?
4. Comparado ao jeito como você faz **isso hoje**, é melhor ou pior - em quê?
5. Em algum momento você achou que tinha feito uma coisa e tinha feito outra? Onde?
6. Houve algum momento em que você **não confiou** no que a ferramenta disse ter feito? *(sondar
   a Tarefa 2 - aceitar o *host key* - e a Tarefa 5/6 - o `apply`/`preview`)*

---

## Parte E - Pontuação e interpretação *(facilitador)*

### E.1 - Escores TAM

Para cada construto, calcule a **média aritmética** dos itens respondidos (escala 1–7):

- **PU** = média(PU1…PU4)
- **PEOU** = média(PE1…PE4)
- **ITU** = média(IT1…IT3)

Não há item reverso no bloco TAM - todas as frases são positivas. Reporte as três médias (e, com
N suficiente, o desvio-padrão). Acima de 4 = inclinação positiva; abaixo de 4 = negativa. O modelo
prevê PU e PEOU como antecedentes da Intenção de Uso `[Davis89]`.

### E.2 - O que transcrever para a folha de observação

```
Participante: P____

TAM:  PU = ____   PEOU = ____   ITU = ____         (escala 1–7)
SC (opcional):  SC1 __  SC2 __  SC3 __

Pós-tarefa (B1 confiança / B2 facilidade, 1–7):
  T1 __/__   T2 __/__   T3 __/__   T4 __/__   T5 __/__   T6 __/__   T7 __/__   T8 __/__   T9 __/__

Alerta de erro perigoso com confiança (B1 alto + tarefa falhada): tarefa(s) nº ________
```

> Cruze a Parte B com a folha de observação do `GUIA_FACILITADOR.md`: toda tarefa marcada como
> **falha** mas com **B1 ≥ 5** é um candidato a "erro perigoso cometido com confiança" - o achado
> mais importante do estudo. Liste essas tarefas explicitamente no relatório da sessão.

---

## Procedência dos itens

De onde vem cada parte do questionário - para citação direta na seção de métodos.

| Parte / item | Procedência | Venue |
|--------------|-------------|-------|
| **A** - demografia e Likert de familiaridade | Smith et al. 2020; Krombholz et al. 2017 | SOUPS 2020; USENIX Security 2017 |
| **A6** - triagem "já conhece a ferramenta?" | Krombholz et al. 2017 (fase de recrutamento/triagem) | USENIX Security 2017 |
| **B1** - confiança / autoavaliação de conclusão por tarefa | Krombholz et al. 2017 - pergunta de saída *"Did you successfully complete the task? (Yes/No/Not sure)"* | USENIX Security 2017 |
| **B2** - dificuldade percebida (Single Ease Question por tarefa) | Krombholz et al. 2017 (Likert de dificuldade); Tiefenau et al. 2019 (formato por subtarefa) | USENIX Security 2017; ACM CCS 2019 |
| **B / E** - noção de "erro perigoso cometido com confiança" | Whitten & Tygar 1999 - as 4 propriedades + o achado clássico | USENIX Security 1999 |
| **C.1** - TAM (PU / PEOU / Intenção de Uso) | Davis 1989 (instrumento; itens adaptados ao AdminForge) | MIS Quarterly 13(3), 1989 |
| **C.2** - confiança e segurança percebida | Whitten & Tygar 1999 (as 4 propriedades); SC2 - dimensão *Transparent* de Tiefenau et al. 2019 | USENIX Security 1999; ACM CCS 2019 |
| **D** - entrevista semiestruturada | Smith et al. 2020 (6 perguntas pós-estudo); Krombholz et al. 2017 (reflexões de saída) | SOUPS 2020; USENIX Security 2017 |
| **E** - rubrica de fechamento (4 propriedades) | Whitten & Tygar 1999 | USENIX Security 1999 |

---

## Referências

- **`[Davis89]`** F. D. Davis. *Perceived usefulness, perceived ease of use, and user acceptance of information technology.* MIS Quarterly 13(3), 1989, pp. 319–340. - instrumento TAM, escala de 7 pontos: PU, PEOU e Intenção de Uso (Parte C.1); itens adaptados ao AdminForge, não verbatim.
- **`[W&T99]`** A. Whitten, J. D. Tygar. *Why Johnny Can't Encrypt.* USENIX Security, 1999. - as 4 propriedades de usabilidade de software de segurança (Parte C.2 e a noção de "erro perigoso", Parte B/E).
- **`[Krombholz17]`** K. Krombholz et al. *"I Have No Idea What I'm Doing" - On the Usability of Deploying HTTPS.* USENIX Security, 2017. - estudo de laboratório com administradores; questionário de entrada + saída, autoavaliação "concluiu? Sim/Não/Não sei" (base da Parte B) e reflexões abertas (Parte D). Não usou SUS/TAM.
- **`[Tiefenau19]`** C. Tiefenau et al. *A Usability Evaluation of Let's Encrypt and Certbot.* ACM CCS, 2019. - RCT com ferramenta CLI para admins; Likert de dificuldade por subtarefa (base da Parte B) e diferencial semântico com a dimensão *Transparent* (base do item C.2 SC2). Não usou SUS/TAM.
- **`[Smith20]`** J. Smith, L. N. Q. Do, E. Murphy-Hill. *Why Can't Johnny Fix Vulnerabilities.* SOUPS, 2020. - estudo moderado de ferramenta de segurança com profissionais; 6 perguntas abertas pós-tarefa (formato da Parte D) e Likert de familiaridade na demografia (Parte A). Não usou SUS/TAM.

Detalhes de cada referência em [`referencias/README.md`](referencias/README.md) e
[`METODOLOGIA-OPCOES.md`](METODOLOGIA-OPCOES.md#referências).
