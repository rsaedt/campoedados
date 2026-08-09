# Base 05 — Canais reais: WhatsApp e Telegram

## Objetivo

Ligar os canais usados pelo operador ao mesmo núcleo homologado nas Bases 01–04.

O canal não contém regra de estoque, fábrica ou financeiro. Ele somente:

1. recebe a mensagem;
2. valida a origem do webhook;
3. identifica o usuário;
4. resolve Agropecuária e unidade padrão;
5. baixa mídia quando houver;
6. entrega texto/áudio/NF ao Agente Operador existente;
7. envia a resposta pelo mesmo canal.

## Identidade do canal

A tabela `channel_identities` liga:

- `channel`: `whatsapp` ou `telegram`;
- `account_key`: número/phone-number-id do WhatsApp ou chave lógica do bot Telegram;
- `external_user_id`: telefone WhatsApp ou id do usuário Telegram;
- `membership_id`: vínculo do usuário com a Agropecuária;
- `default_unit_id`: unidade/fazenda padrão usada como origem do fato operacional.

A combinação `channel + account_key + external_user_id` é única.

Isso permite:

- um único número oficial de WhatsApp atendendo muitos usuários;
- vários bots Telegram, inclusive um por cliente, sem mudar o núcleo;
- o mesmo usuário externo existir em contas diferentes sem colisão;
- impedir que um contato desconhecido escreva no banco operacional.

## Cadastro

Administradores autenticados configuram vínculos por:

- `POST /v1/admin/channel-identities`
- `GET /v1/admin/channel-identities`

Usuários não cadastrados recebem resposta controlada e nenhuma operação é criada.

## WhatsApp

Endpoints:

- `GET /v1/channels/webhooks/whatsapp`: verificação do callback;
- `POST /v1/channels/webhooks/whatsapp`: mensagens recebidas.

Proteções:

- token de verificação no GET;
- assinatura `X-Hub-Signature-256` conferida com o App Secret no POST;
- `message.id` usado como `external_id` do Evento;
- mídia é baixada pela Cloud API usando o `media id`;
- conteúdo segue para a Base 04 e recebe SHA-256 local.

O `CAMPOEDADOS_WHATSAPP_GRAPH_VERSION` é obrigatório e não possui valor fixo no código para evitar envelhecimento silencioso da integração.

## Telegram

Endpoint:

- `POST /v1/channels/webhooks/telegram/{account_key}`

Proteções:

- `X-Telegram-Bot-Api-Secret-Token`;
- `update_id` compõe o identificador idempotente;
- mídia é resolvida com `getFile` e depois baixada;
- a resposta usa `sendMessage`.

É possível configurar um bot simples (`default`) ou múltiplos bots via `CAMPOEDADOS_TELEGRAM_BOTS_JSON`.

## Fluxos

### Texto

`WhatsApp/Telegram → identidade → Agente Operador → Evento → módulos → resposta`

### Áudio

`canal → download → armazenamento original → transcrição → Agente Operador → resposta`

### NF

`canal → download → armazenamento original → visão/extração → estoque/financeiro/gerencial → resposta`

A IA continua sem permissão para alterar estoque diretamente.

## Usuário desconhecido

Um contato não vinculado recebe uma orientação de cadastro e nenhum Evento operacional é criado.

Esse ponto é proposital: cadastro/vendas pode ser acoplado depois, sem misturar contatos externos com dados oficiais.

## Limite desta base

O processamento do webhook é síncrono. Para piloto e homologação isso simplifica o diagnóstico e mantém o fluxo auditável. Antes de escala alta, o próximo passo técnico deve introduzir fila assíncrona/retry interno para desacoplar o tempo de resposta do provedor do tempo de IA e banco.

## Homologação

Os testes cobrem:

- WhatsApp texto → produção;
- reentrega do mesmo webhook sem produção duplicada;
- contato WhatsApp desconhecido sem escrita operacional;
- WhatsApp foto/NF → estoque + Financeiro;
- Telegram texto;
- Telegram áudio;
- segredo Telegram inválido;
- assinatura HMAC real do WhatsApp;
- cadastro administrativo de identidade de canal.
