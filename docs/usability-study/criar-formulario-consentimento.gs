/**
 * AdminForge - gerador do formulário de Termo de Consentimento no Google Forms.
 *
 * Formulário à PARTE, só para o consentimento - separado do questionário
 * (criar-formulario-google.gs) de propósito: o NOME do participante fica só
 * aqui e nunca na mesma planilha que as respostas do estudo. A pseudonimização
 * prometida no termo só se sustenta assim (é o que Krombholz e Tiefenau fazem).
 *
 * Aplicar no início da sessão, antes da Parte A. O campo "Participante (ID)"
 * vincula este consentimento ao questionário, que não traz o nome.
 *
 * COMO USAR:
 *   1. Abra https://script.google.com logado na conta que vai hospedar o form.
 *   2. Novo projeto → apague o conteúdo → cole este arquivo inteiro.
 *   3. Selecione a função "criarFormularioConsentimento" e clique em Executar.
 *   4. Autorize quando o Google pedir (permissão para criar Forms).
 *   5. Veja Execução → registros: as URLs do formulário pronto saem ali.
 */

function criarFormularioConsentimento() {
  var form = FormApp.create('AdminForge - Termo de Consentimento Livre e Esclarecido');

  form.setDescription(
    'Termo de consentimento do estudo de usabilidade do AdminForge. Formulário ' +
    'separado do questionário - o nome informado aqui não fica junto das ' +
    'respostas de pesquisa.'
  );
  form.setCollectEmail(false);
  form.setAllowResponseEdits(false);
  form.setConfirmationMessage('Consentimento registrado. Avise o facilitador.');

  form.addSectionHeaderItem()
    .setTitle('Termo de Consentimento Livre e Esclarecido')
    .setHelpText(
      'Você está sendo convidado(a) a participar de um estudo de usabilidade da ferramenta ' +
      'AdminForge. Você vai realizar tarefas com a ferramenta, narrando seu raciocínio em voz ' +
      'alta, e responder a questionários curtos - cerca de 1 hora. Quem está sendo avaliado é a ' +
      'ferramenta, não você; não há resposta certa ou errada.\n\n' +
      'A sessão terá gravação de tela e de áudio (não há gravação de vídeo da sua imagem).\n\n' +
      'Você será identificado(a) apenas por um pseudônimo (ex.: "P3"): seu nome fica só neste ' +
      'formulário, separado das respostas, e não aparece nos dados analisados nem em publicações.\n\n' +
      'A participação é voluntária - você pode interromper a qualquer momento, sem justificar e ' +
      'sem nenhum prejuízo.'
    );

  form.addCheckboxItem()
    .setTitle('Consentimento')
    .setChoiceValues([
      'Li o termo acima, tive minhas dúvidas esclarecidas e concordo em participar voluntariamente deste estudo.'
    ])
    .setRequired(true);

  form.addTextItem()
    .setTitle('Nome completo')
    .setRequired(true);

  form.addTextItem()
    .setTitle('Participante (ID atribuído pelo facilitador, ex.: P03)')
    .setHelpText('Vincula este consentimento ao questionário - que é identificado só pelo ID, sem o nome.')
    .setRequired(true);

  form.addDateItem()
    .setTitle('Data')
    .setRequired(true);

  Logger.log('Formulário de consentimento criado com sucesso.');
  Logger.log('Editar:    ' + form.getEditUrl());
  Logger.log('Responder: ' + form.getPublishedUrl());
}
