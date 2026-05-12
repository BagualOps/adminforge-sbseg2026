# Como avaliar a usabilidade do AdminForge — opções de metodologia

Documento de decisão. Apresenta as metodologias candidatas para avaliar a usabilidade do
AdminForge, **ranqueadas** pensando em rigor à la USENIX/SOUPS *e* no custo realista pra um
projeto desse tamanho. No fim tem uma **tabela** e uma **lista de bullets pra escolha rápida**.

Os marcadores entre colchetes — `[W&T99]`, `[Smith20]`, `[Jaferian11]`, `[Krombholz17]`,
`[Brooke96]`, `[Davis89]`, `[UTAUT03]` etc. — remetem à seção [Referências](#referências) no
fim, com os links para os papers (USENIX Security, SOUPS, CHI, IEEE S&P) e demais fontes.

## O que estamos avaliando

AdminForge é uma ferramenta de **gestão de identidade privilegiada** numa frota Linux —
no jargão da literatura, uma *IT security management (ITSM) tool* — operada por **CLI** e
voltada a **sysadmins / SRE / DevOps**. A pergunta central é dupla:

1. **Usabilidade / segurança operacional:** um admin de competência mediana, sem ter lido a
   doc, conduz o ciclo (cadastro → grupos → permissão → `apply` → revogação → auditoria) sem
   cometer **erro perigoso** (ex.: conceder `sudo` ao grupo errado, aplicar no servidor errado,
   aceitar *host key* sem validar)?
2. **Aceitação / adoção:** esse admin *usaria* a ferramenta no trabalho? Por quê (não)?

A pergunta 1 é comportamental — pede observação. A pergunta 2 é atitudinal — pede questionário
(é aqui que entra o **TAM/UTAUT**). As metodologias abaixo cobrem uma, a outra, ou as duas.

> **Nota sobre o TAM.** O *Technology Acceptance Model* não é um "método de avaliação" no mesmo
> sentido dos outros — é um **modelo + questionário** que mede Utilidade Percebida (PU),
> Facilidade de Uso Percebida (PEOU) e Intenção de Uso, para prever adoção. Ele aparece aqui
> como **instrumento de medição** que se acopla a um estudo com tarefas (Opção 1) ou a um
> survey leve (Opção 3) — não como uma quinta opção paralela.

---

## Ranking

### 1º — Estudo moderado de laboratório: tarefas + *think-aloud* + questionário pós-teste

**O que é.** Recrutar ~10–15 sysadmins, dar cenários de tarefa num ambiente padronizado
(o lab Docker), pedir que executem narrando o raciocínio em voz alta (*think-aloud*), com um
facilitador observando e cronometrando. Mede **efetividade** (% que completa cada tarefa sem
ajuda, **erros perigosos**), **eficiência** (tempo, nº de `--help`, comandos com erro) e
**satisfação/aceitação** via questionário pós-teste — aqui se escolhe **SUS** (usabilidade
percebida, escore 0–100, benchmark consolidado), **TAM** (PU/PEOU/Intenção), ou os dois. Fecha
com entrevista semiestruturada e análise temática das dificuldades.

**Linhagem USENIX.** É *o* método da área: Whitten & Tygar, *Why Johnny Can't Encrypt* (USENIX
Security 1999, *Test of Time Award*) `[W&T99]`; Smith et al., *Why Can't Johnny Fix Vulnerabilities*
(SOUPS 2020) `[Smith20]` — mesmo formato, ferramenta de segurança, profissionais. Para uma tarefa
de **sysadmin de segurança** (não de usuário final), o análogo direto é Krombholz et al.,
*"I Have No Idea What I'm Doing" — On the Usability of Deploying HTTPS* (USENIX Security 2017)
`[Krombholz17]`: estudo de laboratório com administradores, tarefas, *think-aloud* — exatamente o
que faríamos aqui, trocando "configurar TLS no Apache" por "operar o AdminForge". Veja também
Tiefenau et al. sobre Let's Encrypt/Certbot `[Tiefenau19]`.

**Por que 1º.** É o único que pega o que mais importa numa ferramenta de segurança: o **erro
perigoso cometido com confiança** — inspeção por especialista *adivinha* onde isso pode acontecer;
o teste com usuário *vê* acontecer (W&T relatam ¼ dos participantes enviando o e-mail "secreto"
em claro `[W&T99]`). É o desenho que um *reviewer* de USENIX/SOUPS espera. E acomoda o TAM `[Davis89]`
como instrumento sem abrir mão da observação.

**Custo.** Alto: recrutamento, ~1h por sessão, transcrição/codificação, 2 codificadores numa
fração da amostra. Precisa de gente real.

**Quando escolher.** Se isso vai virar relatório/paper, ou se você quer evidência de verdade de
que a CLI funciona na mão de quem não a escreveu. **Recomendado como base.**

---

### 2º — Combo: inspeção barata (walkthrough cognitivo + heurísticas ITSM) → depois o estudo de laboratório

**O que é.** Antes de chamar participantes, fazer uma passada barata de **walkthrough cognitivo**
(percorrer cada tarefa do roteiro fingindo ser um novato, perguntando em cada passo: o usuário
sabe o que fazer? vê o comando/opção certa? conecta ao objetivo? entende o feedback?) **+
avaliação heurística** contra as **7 heurísticas ITSM** de Jaferian et al. (SOUPS 2011) `[Jaferian11]`
e as 10 de Nielsen `[Nielsen94]` (3–5 avaliadores `[NL93]`). Conserta os problemas óbvios. *Depois*
roda o estudo moderado (Opção 1) com a CLI já desengasgada — assim os participantes não queimam
tempo em bugs triviais que você já sabia.

**Linhagem USENIX.** É literalmente a receita do Whitten & Tygar `[W&T99]` (*cognitive walkthrough*
`[Lewis90]` + *laboratory user test*), modernizada com as heurísticas específicas de ferramentas de
gestão de segurança: Jaferian et al. `[Jaferian11]` mostram que as ITSM pegam problemas severos que
Nielsen sozinho não pega — por isso usar os dois conjuntos.

**Por que 2º (e não 1º).** É a mais completa, mas a parte cara é a mesma da Opção 1; a passada de
inspeção é um **adendo barato**, não uma metodologia separada. Em outras palavras: Opção 2 = Opção
1 + um pré-filtro de meio dia. Se você vai fazer o estudo de lab de qualquer jeito, faça a inspeção
antes — quase de graça.

**Custo.** O da Opção 1 + ~½–1 dia de inspeção (idealmente 2–3 avaliadores).

**Quando escolher.** Se quer o desenho mais defensável e topa o pequeno custo extra. **Recomendado
se for publicar.**

---

### 3º — Survey de aceitação no estilo TAM/UTAUT (exposição curta + questionário)

**O que é.** Dar à pessoa uma exposição *curta* à ferramenta — um demo guiado de 10–15 min, ou
deixar ela mexer um pouco — e o foco é o **questionário TAM** (ou UTAUT): escalas Likert de PU,
PEOU e Intenção de Uso (UTAUT acrescenta influência social e condições facilitadoras, com
moderadores como experiência). Pode ser **remoto e assíncrono**, então escala pra dezenas/centenas
de respostas. Análise: estatística descritiva dos construtos e, com N grande, modelagem
(regressão / PLS-SEM) das relações PU/PEOU → Intenção.

**Linhagem.** TAM `[Davis89]` e UTAUT `[UTAUT03]` são padrão em IS/HCI e aparecem na literatura de
adoção de ferramentas de segurança (treinamento, MFA, gerenciadores de senha, ferramentas de SOC).
É a opção "mais parecida com TAM" porque **é** TAM como protagonista. Aparece com frequência **junto**
de um estudo com tarefas — não como substituto dele.

**Por que 3º.** Responde a pergunta de *adoção* ("usaria?"), não a de *usabilidade operacional*
("consegue usar sem errar?"). Para uma ferramenta de segurança, "o que a pessoa acha" depois de
15 min de demo é um sinal fraco e enviesado (efeito novidade, ela não bateu nas pedras reais).
Ótimo **complemento** de um estudo com tarefas; fraco como **a** avaliação.

**Custo.** Baixo: sem facilitador por sessão, sem transcrição; só montar o questionário e distribuir.

**Quando escolher.** Se a pergunta de negócio for "vale investir nisso? a galera adotaria?" e
você quer N alto rápido — e aceita não saber se eles de fato conseguem operar a coisa.

---

### 4º — Avaliação heurística sozinha (heurísticas ITSM + Nielsen)

**O que é.** 3–5 avaliadores (idealmente com algum traquejo de usabilidade) inspecionam a CLI
de forma independente contra um checklist — as **7 heurísticas ITSM** de Jaferian et al.
(visibilidade do status de atividades; histórico de ações/mudanças nos artefatos; representação
flexível da informação; regras e restrições; planejamento e divisão de trabalho entre usuários;
captura/compartilhamento/descoberta de conhecimento; verificação de conhecimento) **+ as 10 de
Nielsen** — e listam problemas com severidade 0–4. Consolida-se a lista.

**Linhagem USENIX.** As heurísticas ITSM são de um paper SOUPS (Jaferian et al., 2011) `[Jaferian11]`
feito *exatamente* para essa classe de ferramenta — é a inspeção com melhor pedigree pra um ITSM tool.
Para "quantos avaliadores", a regra prática de Nielsen & Landauer `[NL93]`: 3–5 já pegam a maioria.

**Por que 4º.** Não precisa de usuário, é rápido e barato — mas só acha **problema de interface**,
não mede se o admin real completa as tarefas nem flagra o erro perigoso *na prática*. Ótimo como
**componente** (é a inspeção da Opção 2); fraco como avaliação inteira.

**Custo.** Baixo: alguns dias de 3–5 avaliadores; sem recrutamento de participantes.

**Quando escolher.** Sem orçamento/tempo pra participantes, ou como faxina antes de um estudo maior.

---

### 5º — Cognitive walkthrough sozinho

**O que é.** Um ou mais especialistas percorrem cada tarefa do roteiro **passo a passo**, na pele
de um sysadmin novato, respondendo as 4 perguntas do walkthrough em cada passo (o usuário vai saber
o que fazer? vai localizar o comando/flag certo? vai associá-lo ao objetivo? vai entender o
feedback/resultado?). Saída: para cada passo, "passa" ou "trava — porquê".

**Linhagem USENIX.** Método padrão de inspeção `[Lewis90]`; foi *uma das duas pernas* do Whitten &
Tygar `[W&T99]` (a outra foi o teste de laboratório).

**Por que 5º.** O mais barato de todos e bem focado em **descoberta** ("dá pra figurar sem ler a
doc?"), que é metade do problema. Mas é o de menor cobertura — não fala de eficiência, de satisfação
nem de erro perigoso fora do fluxo previsto. Melhor como **componente** (a outra metade da inspeção
da Opção 2).

**Custo.** O mais baixo: meio dia de 1–2 especialistas.

**Quando escolher.** Faxina mínima antes de qualquer coisa maior; ou quando só interessa "um
recém-chegado consegue se virar?".

---

## Tabela comparativa

Panorama enxuto (5 colunas, pra caber na página). As citações USENIX/SOUPS e o "papel" de cada
opção estão na prosa de cada item, acima.

| Opção | Participantes | Erro perigoso na prática | Adoção (TAM) | Custo |
|---|---|---|---|---|
| 1 — Lab moderado: tarefas + think-aloud + SUS/TAM | ~10–15 | sim | sim, com TAM no fim | alto |
| 2 — Combo: inspeção (walkthrough + ITSM) e depois o lab moderado | ~10–15 + 2–3 avaliadores | sim | sim | alto+ |
| 3 — Survey estilo TAM/UTAUT (exposição curta + questionário) | remoto, N alto | não | sim — protagonista | baixo |
| 4 — Avaliação heurística (ITSM + Nielsen) | 3–5 avaliadores | não | não | baixo |
| 5 — Cognitive walkthrough | 1–2 especialistas | não | não | muito baixo |

**Pedigree resumido:** opção 1 → Whitten & Tygar (USENIX Security'99), Smith et al. (SOUPS'20),
Krombholz et al. (USENIX Security'17); opção 2 → o combo do Whitten & Tygar + heurísticas ITSM de
Jaferian et al. (SOUPS'11); opção 3 → Davis (TAM'89), Venkatesh et al. (UTAUT'03); opções 4 e 5 →
Jaferian et al. (SOUPS'11) / Nielsen / Lewis et al. (componentes da opção 2).

---

## Escolha rápida (sem ler o resto)

- **Quer o jeito "USENIX" de avaliar uma ferramenta de segurança, com evidência de verdade →** Opção **1** (estudo moderado de lab + questionário pós-teste). É a base. Recomendado.
- **Mesma coisa, mas isso vai virar relatório/paper e você topa ½ dia a mais →** Opção **2** (faz uma faxina barata de inspeção antes). Recomendado se for publicar.
- **A pergunta de verdade é "sysadmin adotaria isso?" e você quer muitas respostas rápido →** Opção **3** (survey TAM/UTAUT). É a "mais parecida com TAM" porque o TAM é o protagonista. Aceita não medir se a pessoa *consegue* operar.
- **Não tem como recrutar participantes agora →** Opção **4** ou **5** (inspeção). Barato e rápido, mas é diagnóstico de interface, não prova que funciona na mão de ninguém. Trate como provisório.
- **Quer o TAM mas sem perder a parte comportamental →** não escolha entre eles: Opção **1 com o instrumento pós-teste = TAM** (e SUS junto, se quiser comparar com o benchmark). É o uso clássico do TAM em HCI.

**Recomendação:** começar pela **Opção 1** com **TAM + SUS** no pós-teste; se houver fôlego, virar **Opção 2** (acrescenta a passada de inspeção ITSM/Nielsen antes de chamar os participantes). O survey TAM puro (Opção 3) fica como rodada futura, se quiser número grande de respostas sobre intenção de adoção.

---

## Referências

### USENIX Security / SOUPS — estudos de usabilidade de ferramentas de segurança

- **`[W&T99]`** A. Whitten, J. D. Tygar. *Why Johnny Can't Encrypt: A Usability Evaluation of PGP 5.0.* 8th USENIX Security Symposium, 1999. — *USENIX Security Test of Time Award, 2015.* Define o que é "usável" para software de segurança (as 4 propriedades) e combina *cognitive walkthrough* + teste de laboratório. https://www.usenix.org/conference/8th-usenix-security-symposium/why-johnny-cant-encrypt-usability-evaluation-pgp-50 — PDF: https://www.usenix.org/legacy/events/sec99/full_papers/whitten/whitten.pdf
- **`[Smith20]`** J. Smith, L. N. Q. Do, E. Murphy-Hill. *Why Can't Johnny Fix Vulnerabilities: A Usability Evaluation of Static Analysis Tools for Security.* SOUPS 2020 (USENIX). Estudo moderado de laboratório de uma ferramenta de segurança com profissionais; tarefas, *think-aloud*, entrevista, análise temática — o template metodológico mais próximo do nosso caso. https://www.usenix.org/conference/soups2020/presentation/smith — PDF: https://www.usenix.org/system/files/soups2020-smith.pdf
- **`[Krombholz17]`** K. Krombholz, W. Mayer, M. Schmiedecker, E. Weippl. *"I Have No Idea What I'm Doing" — On the Usability of Deploying HTTPS.* 26th USENIX Security Symposium, 2017. Estudo de laboratório com **administradores de sistemas** executando uma tarefa de segurança real (configurar TLS) — o análogo direto do AdminForge. https://www.usenix.org/conference/usenixsecurity17/technical-sessions/presentation/krombholz — PDF: https://www.usenix.org/system/files/conference/usenixsecurity17/sec17-krombholz.pdf
- **`[Tiefenau19]`** C. Tiefenau, E. von Zezschwitz, M. Häring, K. Krombholz, M. Smith. *A Usability Evaluation of Let's Encrypt and Certbot: Usable Security Done Right.* ACM CCS 2019. Avaliação de usabilidade de uma ferramenta de linha de comando voltada a admins — bom contraponto "feito direito". https://dl.acm.org/doi/10.1145/3319535.3363220
- **`[Jaferian11]`** P. Jaferian, K. Hawkey, A. Sotirakopoulos, M. Velez-Rojas, K. Beznosov. *Heuristics for Evaluating IT Security Management Tools.* SOUPS 2011 (versão curta em CHI EA 2011; versão estendida em *Human–Computer Interaction* 29(4), 2014). Propõe e valida as 7 heurísticas ITSM; mostra que pegam problemas severos que as de Nielsen não pegam. PDF (SOUPS 2011): https://cups.cs.cmu.edu/soups/2011/proceedings/a7_Jaferian.pdf — ACM: https://dl.acm.org/doi/10.1145/2078827.2078837
- SOUPS — *Symposium on Usable Privacy and Security* (co-localizado com USENIX Security desde 2018): índice de proceedings em https://www.usenix.org/conferences/byname/6

### Instrumentos de medição

- **`[Brooke96]`** J. Brooke. *SUS — A "quick and dirty" usability scale.* In P. W. Jordan et al. (eds.), *Usability Evaluation in Industry*, Taylor & Francis, 1996, pp. 189–194. Escala de 10 itens, escore 0–100. Benchmark consolidado (Sauro & Lewis): média ≈ 68; ≥ 80 ≈ topo-10%. PDF do original: https://digital.ahrq.gov/sites/default/files/docs/survey/systemusabilityscale(sus)_comp[1].pdf
- **`[Davis89]`** F. D. Davis. *Perceived usefulness, perceived ease of use, and user acceptance of information technology.* *MIS Quarterly* 13(3), 1989, pp. 319–340. O TAM original (PU, PEOU → Intenção de Uso → Uso). https://www.jstor.org/stable/249008
- **`[UTAUT03]`** V. Venkatesh, M. G. Morris, G. B. Davis, F. D. Davis. *User acceptance of information technology: Toward a unified view.* *MIS Quarterly* 27(3), 2003, pp. 425–478. O UTAUT (expectativa de desempenho/esforço, influência social, condições facilitadoras + moderadores). https://www.jstor.org/stable/30036540

### Métodos de inspeção e bases

- **`[Lewis90]`** C. Lewis, P. Polson, C. Wharton, J. Rieman. *Testing a walkthrough methodology for theory-based design of walk-up-and-use interfaces.* CHI 1990, pp. 235–242. O *cognitive walkthrough*. https://dl.acm.org/doi/10.1145/97243.97279
- **`[Nielsen94]`** J. Nielsen. *Heuristic evaluation.* In J. Nielsen & R. L. Mack (eds.), *Usability Inspection Methods*, Wiley, 1994. As 10 heurísticas de usabilidade. https://www.nngroup.com/articles/ten-usability-heuristics/
- **`[NL93]`** J. Nielsen, T. K. Landauer. *A mathematical model of the finding of usability problems.* INTERCHI 1993, pp. 206–213. Justifica 3–5 avaliadores/participantes para pegar a maioria dos problemas. https://dl.acm.org/doi/10.1145/169059.169166
- **`[ISO11]`** ISO 9241-11:2018 — *Ergonomics of human-system interaction — Part 11: Usability: Definitions and concepts.* As três dimensões: efetividade, eficiência, satisfação. https://www.iso.org/standard/63500.html
