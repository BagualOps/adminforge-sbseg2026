/**
 * AdminForge - gerador do questionário de usabilidade no Google Forms.
 *
 * Cria UM único Google Form, espelhando o QUESTIONARIO.md:
 *   - Parte A (perfil) - preenchida no início da sessão;
 *   - 9 seções de tarefa (Parte B) - cada uma preenchida logo após a tarefa;
 *   - Parte C (TAM + bloco de confiança/segurança) - preenchida no fim.
 * O participante mantém a mesma aba aberta a sessão inteira e envia 1 vez.
 *
 * As Partes D (entrevista) e E (pontuação) NÃO entram aqui: D é conduzida ao
 * vivo pelo facilitador; E é cálculo posterior (médias TAM a partir da planilha
 * de respostas - ver Parte E do QUESTIONARIO.md).
 *
 * COMO USAR:
 *   1. Abra https://script.google.com logado na conta que vai hospedar o form.
 *   2. Novo projeto → apague o conteúdo → cole este arquivo inteiro.
 *   3. Selecione a função "criarFormulario" e clique em Executar.
 *   4. Autorize quando o Google pedir (permissão para criar Forms).
 *   5. Veja o menu Execução → registros: as URLs de edição e de resposta
 *      do formulário pronto são impressas ali.
 */

function criarFormulario() {
  var form = FormApp.create('Estudo de usabilidade do AdminForge - questionário');

  form.setDescription(
    'Questionário do estudo de usabilidade do AdminForge ' +
    '(Opção 1 - estudo moderado de laboratório). O termo de consentimento é um ' +
    'formulário separado (criar-formulario-consentimento.gs).\n\n' +
    'Preencha a Parte A no início; cada seção de tarefa LOGO APÓS terminar a ' +
    'tarefa correspondente, antes de seguir; e a Parte C ao final, antes da ' +
    'entrevista. Mantenha esta aba aberta durante toda a sessão e envie só uma ' +
    'vez, no fim. Não há resposta certa - quem está sendo avaliado é a ferramenta.'
  );
  form.setProgressBar(true);
  form.setCollectEmail(false);
  form.setAllowResponseEdits(false);
  form.setConfirmationMessage('Respostas registradas. Avise o facilitador - obrigado!');

  var cols5 = ['1', '2', '3', '4', '5'];
  var cols7 = ['1', '2', '3', '4', '5', '6', '7'];

  // ----------------------------------------------------------------------
  // PARTE A - Perfil
  // ----------------------------------------------------------------------
  form.addSectionHeaderItem()
    .setTitle('Parte A - Perfil')
    .setHelpText('Preencher antes da Tarefa 0. Caracteriza a amostra; não há resposta certa.');

  form.addTextItem().setTitle('Participante (ID atribuído pelo facilitador, ex.: P03)');

  form.addTextItem().setTitle('A1. Cargo / função atual');

  form.addMultipleChoiceItem()
    .setTitle('A2. Há quanto tempo você administra servidores Linux profissionalmente?')
    .setChoiceValues(['menos de 1 ano', '1 a 3 anos', '3 a 7 anos', 'mais de 7 anos']);

  form.addMultipleChoiceItem()
    .setTitle('A3. Tamanho aproximado da frota de servidores que você administra hoje')
    .setChoiceValues(['não administro uma frota', '1–10', '11–50', '51–200', 'mais de 200']);

  var a4 = form.addCheckboxItem()
    .setTitle('A4. Como você gerencia acesso SSH e sudo hoje? (marque todas que se aplicam)');
  a4.setChoiceValues([
    'manualmente, servidor a servidor (editar authorized_keys / sudoers à mão)',
    'Ansible / Puppet / Chef / Salt ou similar',
    'FreeIPA / LDAP / Active Directory / Kerberos',
    'scripts próprios'
  ]);
  a4.showOtherOption(true);

  form.addGridItem()
    .setTitle('A5. Avalie sua familiaridade com cada item')
    .setHelpText('1 = nenhuma · 5 = muita')
    .setRows([
      'Linha de comando / terminal Linux',
      'Chaves SSH e fingerprints de host',
      'Configuração de sudo / sudoers',
      'Ferramentas declarativas / infra as code',
      'Conceitos de segurança operacional (hardening, privilégio mínimo, auditoria)'
    ])
    .setColumns(cols5);

  form.addMultipleChoiceItem()
    .setTitle('A6. Você já conhecia ou usou o AdminForge antes desta sessão?')
    .setChoiceValues(['nunca ouvi falar', 'já ouvi falar, nunca usei', 'já usei']);

  // ----------------------------------------------------------------------
  // PARTE B - 9 seções de tarefa (uma página por tarefa)
  // ----------------------------------------------------------------------
  var tarefas = [
    'Tarefa 1 - Cadastrar a Alice e a chave dela',
    'Tarefa 2 - Cadastrar a frota (web-01, web-02, db-03)',
    'Tarefa 3 - Organizar em grupos',
    'Tarefa 4 - Conceder os acessos',
    'Tarefa 5 - Aplicar e conferir',
    'Tarefa 6 - Sudo limitado no banco',
    'Tarefa 7 - Offboarding da Alice',
    'Tarefa 8 - Investigar o web-02 (se houver tempo)',
    'Tarefa 9 - Histórico da sessão (se houver tempo)'
  ];

  for (var i = 0; i < tarefas.length; i++) {
    form.addPageBreakItem()
      .setTitle(tarefas[i])
      .setHelpText('Preencha LOGO APÓS terminar esta tarefa, antes de seguir para a ' +
                   'próxima. Se não realizou esta tarefa, deixe em branco.');

    form.addScaleItem()
      .setTitle('B1. Quão confiante você está de que concluiu esta tarefa corretamente?')
      .setBounds(1, 7)
      .setLabels('Nada confiante', 'Totalmente confiante');

    form.addScaleItem()
      .setTitle('B2. No geral, realizar esta tarefa foi:')
      .setBounds(1, 7)
      .setLabels('Muito difícil', 'Muito fácil');

    form.addParagraphTextItem()
      .setTitle('B3. (opcional) O que mais te atrapalhou ou te deu segurança nesta tarefa?');
  }

  // ----------------------------------------------------------------------
  // PARTE C - Questionário pós-teste (TAM + confiança/segurança)
  // ----------------------------------------------------------------------
  form.addPageBreakItem()
    .setTitle('Parte C - Questionário pós-teste')
    .setHelpText('Responder UMA vez, após a Tarefa 9 e antes da entrevista. ' +
                 'Marque sua primeira reação a cada frase, sem pensar demais.');

  // C.1 - TAM
  form.addSectionHeaderItem()
    .setTitle('C.1 - TAM (Technology Acceptance Model)')
    .setHelpText('1 = Discordo totalmente · 7 = Concordo totalmente.');

  form.addGridItem()
    .setTitle('Utilidade Percebida (PU)')
    .setRows([
      'PU1. Usar o AdminForge me permitiria realizar tarefas de gestão de acesso mais rapidamente.',
      'PU2. Usar o AdminForge melhoraria meu desempenho na administração de acesso da frota.',
      'PU3. Usar o AdminForge reduziria a chance de eu cometer um erro de acesso ou de sudo.',
      'PU4. De forma geral, eu consideraria o AdminForge útil no meu trabalho.'
    ])
    .setColumns(cols7);

  form.addGridItem()
    .setTitle('Facilidade de Uso Percebida (PEOU)')
    .setRows([
      'PE1. Aprender a operar o AdminForge foi fácil para mim.',
      'PE2. Achei fácil fazer o AdminForge fazer o que eu queria.',
      'PE3. Minha interação com o AdminForge foi clara e compreensível.',
      'PE4. De forma geral, achei o AdminForge fácil de usar.'
    ])
    .setColumns(cols7);

  form.addGridItem()
    .setTitle('Intenção de Uso (ITU)')
    .setRows([
      'IT1. Se o AdminForge estivesse disponível no meu trabalho, eu pretenderia usá-lo para gerenciar acesso.',
      'IT2. Eu preferiria usar o AdminForge ao jeito como faço a gestão de acesso hoje.',
      'IT3. Eu recomendaria o AdminForge a um colega que administra uma frota Linux.'
    ])
    .setColumns(cols7);

  // C.2 - Confiança e segurança percebida (opcional)
  form.addSectionHeaderItem()
    .setTitle('C.2 - Confiança e segurança percebida (itens complementares)')
    .setHelpText('Itens próprios, fora do escore do TAM. 1 = Discordo totalmente · ' +
                 '7 = Concordo totalmente.');

  form.addGridItem()
    .setTitle('Confiança e segurança')
    .setRows([
      'SC1. Confio que os acessos da frota ficaram exatamente como eu pretendia.',
      'SC2. A ferramenta deixou claro, antes de eu confirmar, o que cada ação faria nos servidores.',
      'SC3. Senti que a ferramenta me protegeria de cometer um erro perigoso (ex.: dar sudo ao grupo ou servidor errado).'
    ])
    .setColumns(cols7);

  // ----------------------------------------------------------------------
  Logger.log('Formulário criado com sucesso.');
  Logger.log('Editar:    ' + form.getEditUrl());
  Logger.log('Responder: ' + form.getPublishedUrl());
}
