# Referências — Método 1 (estudo moderado de laboratório)

Artigos citados na metodologia escolhida (Opção 1 de [`../METODOLOGIA-OPCOES.md`](../METODOLOGIA-OPCOES.md)).
Os marcadores `[...]` são os usados naquele documento.

## Baixados

| Marcador | Arquivo | Referência |
|----------|---------|------------|
| `[W&T99]` | `whitten-tygar-1999-why-johnny-cant-encrypt.pdf` | A. Whitten, J. D. Tygar. *Why Johnny Can't Encrypt: A Usability Evaluation of PGP 5.0.* 8th USENIX Security Symposium, 1999. — define a usabilidade de software de segurança (4 propriedades) + cognitive walkthrough × teste de laboratório. |
| `[Smith20]` | `smith-2020-why-cant-johnny-fix-vulnerabilities.pdf` | J. Smith, L. N. Q. Do, E. Murphy-Hill. *Why Can't Johnny Fix Vulnerabilities: A Usability Evaluation of Static Analysis Tools for Security.* SOUPS 2020 — o template metodológico mais próximo (estudo moderado de uma ferramenta de segurança com profissionais). |
| `[Krombholz17]` | `krombholz-2017-usability-deploying-https.pdf` | K. Krombholz et al. *"I Have No Idea What I'm Doing" — On the Usability of Deploying HTTPS.* 26th USENIX Security Symposium, 2017 — estudo de laboratório com sysadmins numa tarefa de segurança real (o análogo direto do AdminForge). |
| `[Tiefenau19]` | `tiefenau-2019-letsencrypt-certbot.pdf` | C. Tiefenau et al. *A Usability Evaluation of Let's Encrypt and Certbot: Usable Security Done Right.* ACM CCS 2019 — RCT/within-subjects de uma ferramenta de linha de comando voltada a admins. |
| `[Brooke96]` | `brooke-1996-system-usability-scale.pdf` | J. Brooke. *SUS — A "quick and dirty" usability scale.* In *Usability Evaluation in Industry*, 1996 — o instrumento SUS (questionário pós-teste). |
| — | `brooke-2013-sus-retrospective.pdf` | J. Brooke. *SUS: A Retrospective.* Journal of Usability Studies, 2013 — retrospectiva do próprio autor (benchmark, interpretação do escore). Bônus. |
| `[Jaferian11]` | `jaferian-2011-heuristics-itsm-tools.pdf` | P. Jaferian et al. *Heuristics for Evaluating IT Security Management Tools.* SOUPS 2011 — as 7 heurísticas ITSM (avaliação por especialista; usada na Opção 2/combo). |

## Faltando — instrumento TAM

São de **acesso aberto** na AIS Electronic Library (não precisam de assinatura), mas o
download via script é bloqueado por anti-bot — baixar **pelo navegador**:

| Marcador | Referência | Link (open access) |
|----------|------------|--------------------|
| `[Davis89]` | F. D. Davis. *Perceived usefulness, perceived ease of use, and user acceptance of information technology.* MIS Quarterly 13(3), 1989 — o **TAM**. | https://aisel.aisnet.org/misq/vol13/iss3/6/ |
| `[UTAUT03]` | V. Venkatesh et al. *User acceptance of information technology: Toward a unified view.* MIS Quarterly 27(3), 2003 — o **UTAUT**. | https://aisel.aisnet.org/misq/vol27/iss3/5 |

> Para o **Método 1** o núcleo (`[W&T99]`, `[Smith20]`, `[Krombholz17]`, `[Tiefenau19]`) e o
> instrumento SUS (`[Brooke96]`) estão aqui. Falta só o TAM (`[Davis89]`) — abrir o link da AISeL no
> navegador e salvar como `davis-1989-tam.pdf` nesta pasta. `[UTAUT03]` só é necessário se o
> questionário pós-teste for usar UTAUT em vez de TAM.
