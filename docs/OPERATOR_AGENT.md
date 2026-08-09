# Agente Operador — Base 02

O Agente Operador é uma porta de entrada transversal aos módulos do Campo e Dados.

## Princípios

- o operador relata o fato; não preenche um ERP;
- a mensagem original é preservada no Evento;
- o agente interpreta e roteia somente para módulos habilitados;
- além do módulo contratado, o usuário precisa de permissão `can_register`;
- informação incompleta vira `waiting_complement`;
- não conformidade de estoque vira `waiting_manager`, sem baixa parcial;
- operação normal é processada e auditada.

## Primeiro fluxo homologável

Envelope da integração/API:

```json
{
  "text": "Fiz 3 batidas da Seca 0,1",
  "unit_code": "SH7",
  "channel": "api"
}
```

Resultado esperado:

1. autentica o operador pelo token do vínculo com a Agropecuária;
2. valida que Fábrica de Ração está contratada;
3. valida `can_register` para o operador;
4. identifica `feed_mill.production`;
5. encontra a fórmula `Seca 0,1`;
6. extrai `3` batidas;
7. preserva a frase original no evento;
8. valida todos os ingredientes antes de qualquer baixa;
9. executa a produção e forma o custo;
10. marca o evento como `processed` e grava auditoria.

## Interpretação

A Base 02 usa um interpretador determinístico em português para tornar a homologação repetível e independente de serviços externos. A interface de fluxo foi separada para permitir posterior substituição/combinação com interpretação por IA sem alterar estoque, eventos ou permissões.

## Idempotência de canais

Integrações podem enviar `external_id` (por exemplo o ID da mensagem do WhatsApp/Telegram). O trio `organização + canal + external_id` é único. Reentregas retornam o evento já existente e nunca repetem a movimentação física/financeira.
