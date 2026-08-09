# Base 04 — Entrada multimodal

## Objetivo

Fazer texto, voz, foto e PDF convergirem para o mesmo núcleo de Eventos do Campo e Dados.

## Princípio

A IA interpreta. As regras de negócio decidem.

A IA nunca altera estoque ou Financeiro diretamente. Ela devolve texto/transcrição ou dados estruturados; depois o motor existente valida módulos, permissões, cadastros, estoque, custos, duplicidades e aprovações.

## NF em foto/PDF

`POST /v1/operator/media/invoice`

Fluxo:

1. autentica o usuário;
2. recebe imagem/PDF;
3. preserva o arquivo original em armazenamento;
4. calcula SHA-256;
5. envia o documento à camada de visão;
6. recebe JSON estruturado da NF;
7. aplica quantidade física informada pelo operador, quando houver;
8. transforma a leitura em `OperatorDocumentInput`;
9. executa o mesmo motor de recebimento da Base 03;
10. registra EventDocument, auditoria, estoque e Financeiro conforme os módulos contratados.

### Dados extraídos

- fornecedor;
- CNPJ/CPF quando visível;
- número da NF;
- data de emissão;
- itens;
- quantidade/unidade;
- valor unitário;
- valor total;
- parcelas/vencimentos quando realmente presentes;
- confiança e observações do extrator.

Nenhum vencimento ou valor ausente deve ser inventado.

## Financeiro incompleto não bloqueia o físico

Se a NF permitir identificar produto, quantidade e custo, mas não trouxer parcelas/vencimentos:

- Fábrica de Ração: `processed`;
- Financeiro: `waiting_complement`;
- estoque físico é atualizado;
- compra/contas a pagar ainda não são criadas;
- o evento preserva quais campos financeiros faltam.

## Quantidade física x NF

O formulário aceita `received_quantity` e `received_unit`.

Exemplo:

- NF: 30.000 kg;
- operador informa recebido: 29.400 kg;
- estoque: +29.400 kg;
- diferença: -600 kg;
- fluxo já existente de não conformidade/Gerencial é acionado.

## Áudio

`POST /v1/operator/media/audio`

Fluxo:

1. preserva o áudio original;
2. calcula SHA-256;
3. transcreve em português;
4. usa a transcrição como `source_original` operacional;
5. passa pelo mesmo Agente Operador.

Exemplo:

`Fiz 3 batidas da Seca 0,1`

segue exatamente a mesma regra de produção de uma mensagem digitada.

## Idempotência

Existem duas proteções complementares:

- `organização + canal + external_id` para reentrega do webhook;
- SHA-256 do arquivo para o mesmo documento reenviado com outro ID.

Para NF, número + fornecedor também é comparado quando disponível.

## Configuração

Variáveis:

- `OPENAI_API_KEY`;
- `CAMPOEDADOS_OPENAI_VISION_MODEL` (padrão `gpt-5-mini`);
- `CAMPOEDADOS_OPENAI_TRANSCRIBE_MODEL` (padrão `gpt-4o-mini-transcribe`);
- `CAMPOEDADOS_UPLOAD_DIR`;
- `CAMPOEDADOS_MAX_UPLOAD_BYTES`.

A chave nunca deve ser versionada no GitHub.

## Limites deliberados desta base

- NF com múltiplos itens é lida, mas não é lançada automaticamente como várias entradas; vai para complemento/revisão até o fluxo multi-item ser homologado.
- armazenamento atual é filesystem por adaptador; produção poderá substituir por S3/Supabase Storage sem alterar a API de negócio.
- integração direta com webhook do WhatsApp/Telegram será uma camada de canal sobre estes endpoints/serviços.
