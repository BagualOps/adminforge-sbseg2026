/**
 * AdminForge - gerador da folha de observação do FACILITADOR no Google Forms.
 *
 * Versão digital da "Folha de observação" do GUIA_FACILITADOR.md (seção 5).
 * É preenchida pelo FACILITADOR (não pelo participante), um formulário por
 * participante/sessão. Cobre:
 *   - cabeçalho da sessão;
 *   - métricas por tarefa (Tarefas 1–9): resultado, tempo, nº de --help,
 *     nível de dica, erro perigoso;
 *   - episódios de dificuldade;
 *   - rubrica das 4 propriedades de Whitten & Tygar;
 *   - notas da entrevista semiestruturada (Parte D);
 *   - observações finais.
 *
 * O questionário respondido pelo PARTICIPANTE (Partes A/B/C) é gerado pelo
 * outro script: criar-formulario-google.gs.
 *
 * COMO USAR:
 *   1. Abra https://script.google.com logado na conta que vai hospedar o form.
 *   2. Novo projeto → apague o conteúdo → cole este arquivo inteiro.
 *   3. Selecione a função "criarFormularioFacilitador" e clique em Executar.
 *   4. Autorize quando o Google pedir (permissão para criar Forms).
 *   5. Veja Execução → registros: as URLs do formulário pronto saem ali.
 */

function criarFormularioFacilitador() {
  var form = FormApp.create('AdminForge - folha de observação do facilitador');

  form.setDescription(
    'Folha de observação do estudo de usabilidade do AdminForge - preenchida pelo ' +
    'FACILITADOR, um formulário por participante. Companion do GUIA_FACILITADOR.md ' +
    '(seção 5). Não mostrar ao participante. Preencha durante e logo após a sessão.'
  );
  form.setProgressBar(true);
  form.setCollectEmail(false);
  form.setAllowResponseEdits(true);
  form.setConfirmationMessage('Folha registrada. Rode o lab/reset.sh antes do próximo participante.');

  // ----------------------------------------------------------------------
  // CABEÇALHO DA SESSÃO
  // ----------------------------------------------------------------------
  form.addSectionHeaderItem()
    .setTitle('Cabeçalho da sessão');

  form.addTextItem().setTitle('Participante (ID, ex.: P03)');
  form.addDateItem().setTitle('Data da sessão');
  form.addTextItem().setTitle('Facilitador (nome)');
  form.addParagraphTextItem()
    .setTitle('Tarefa 0 - primeira impressão')
    .setHelpText('Aquecimento, não cronometrar. Anote a frase de primeira impressão (verbatim).');

  // ----------------------------------------------------------------------
  // MÉTRICAS POR TAREFA - uma página por tarefa (Tarefas 1–9)
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
      .setHelpText('Se a tarefa não foi realizada, deixe em branco.');

    form.addMultipleChoiceItem()
      .setTitle('Resultado')
      .setChoiceValues(['sucesso sem ajuda', 'sucesso com ajuda', 'falha']);

    form.addTextItem()
      .setTitle('Tempo (minutos)');

    form.addTextItem()
      .setTitle('Nº de --help / -h');

    form.addMultipleChoiceItem()
      .setTitle('Maior nível de dica usado')
      .setChoiceValues([
        'nenhum',
        'Nível 1 - reorienta (não entrega)',
        'Nível 2 - aponta o caminho',
        'Mostrar - facilitador executa/explica (falha assistida)'
      ]);

    form.addMultipleChoiceItem()
      .setTitle('Erro perigoso?')
      .setHelpText('Executou (ou estava a um Enter de executar) ação destrutiva/insegura achando que estava certa.')
      .setChoiceValues(['não', 'sim']);

    form.addParagraphTextItem()
      .setTitle('Erro perigoso - descrição verbatim / outras notas da tarefa')
      .setHelpText('Se houve erro perigoso, transcreva verbatim o que a pessoa disse/fez.');
  }

  // ----------------------------------------------------------------------
  // EPISÓDIOS DE DIFICULDADE
  // ----------------------------------------------------------------------
  form.addPageBreakItem().setTitle('Episódios de dificuldade');
  form.addParagraphTextItem()
    .setTitle('Onde travou / o que disse / o que tentou')
    .setHelpText('Registre verbatim os momentos de dificuldade ao longo da sessão.');

  // ----------------------------------------------------------------------
  // RUBRICA DE WHITTEN & TYGAR (4 propriedades)
  // ----------------------------------------------------------------------
  form.addPageBreakItem()
    .setTitle('Rubrica de Whitten & Tygar')
    .setHelpText('As 4 propriedades de usabilidade de software de segurança. Marque sim / parcial / não.');

  form.addGridItem()
    .setTitle('O participante…')
    .setRows([
      '(1) foi informado de forma confiável das tarefas de segurança que precisava realizar',
      '(2) conseguiu descobrir como executá-las com sucesso',
      '(3) não cometeu erros perigosos',
      '(4) ficou suficientemente confortável com a interface para continuar usando'
    ])
    .setColumns(['sim', 'parcial', 'não']);

  form.addParagraphTextItem()
    .setTitle('Evidência de cada propriedade')
    .setHelpText('Uma frase de evidência por propriedade - numere de 1 a 4.');

  // ----------------------------------------------------------------------
  // ENTREVISTA SEMIESTRUTURADA (Parte D)
  // ----------------------------------------------------------------------
  form.addPageBreakItem()
    .setTitle('Entrevista semiestruturada (Parte D)')
    .setHelpText('Registre as falas principais; o áudio gravado é a fonte completa.');

  var perguntasEntrevista = [
    'D1. Qual foi o pior momento da sessão? E o melhor?',
    'D2. O que você mudaria na ferramenta, se pudesse mudar uma coisa?',
    'D3. Você usaria o AdminForge no seu trabalho? Por quê / por que não?',
    'D4. Comparado ao jeito como você faz isso hoje, é melhor ou pior - em quê?',
    'D5. Em algum momento você achou que tinha feito uma coisa e tinha feito outra? Onde?',
    'D6. Houve algum momento em que você não confiou no que a ferramenta disse ter feito?'
  ];
  for (var j = 0; j < perguntasEntrevista.length; j++) {
    form.addParagraphTextItem().setTitle(perguntasEntrevista[j]);
  }
  form.addParagraphTextItem().setTitle('Citações marcantes da entrevista');

  // ----------------------------------------------------------------------
  // OBSERVAÇÕES FINAIS
  // ----------------------------------------------------------------------
  form.addPageBreakItem().setTitle('Observações finais');
  form.addParagraphTextItem().setTitle('Observações finais da sessão');

  // ----------------------------------------------------------------------
  Logger.log('Formulário do facilitador criado com sucesso.');
  Logger.log('Editar:    ' + form.getEditUrl());
  Logger.log('Responder: ' + form.getPublishedUrl());
}
