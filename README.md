# Campo e Dados

> Marca: **Campo & Dados**  
> Produto/sistema: **Campo e Dados**

Plataforma modular para coleta, interpretação e gestão de dados operacionais no campo.

## Regra de contratação

Cada organização pode contratar e habilitar **um, vários ou todos os módulos**, em qualquer combinação. Nenhum módulo é comercialmente obrigatório para habilitar outro.

Módulos iniciais:

- **M01 — Pecuária**: coleta e estruturação de movimentações e ocorrências pecuárias.
- **M02 — Fábrica de Ração**: insumos, fórmulas, produção, estoque, custos e transferências.
- **M03 — Financeiro**: compras, fornecedores, contas a pagar, parcelas, centros de custo e rateios.

## Núcleo compartilhado

O núcleo concentra:

- organizações e unidades;
- usuários, vínculos e permissões;
- habilitação independente de módulos;
- eventos de campo e interpretação;
- aprovação gerencial;
- auditoria;
- identidades de WhatsApp/Telegram;
- arquivos originais e entrada multimodal.

## Capacidades atuais

- Agente Operador por API, WhatsApp ou Telegram;
- texto, áudio, foto e PDF;
- leitura estruturada de NF e transcrição de áudio;
- produção de ração com baixa de ingredientes e custo bruto aproximado;
- estoque valorizado por unidade;
- transferência entre fazendas carregando quantidade e valor;
- não conformidades e Agente Gerencial;
- compra e contas a pagar na organização/Agropecuária;
- contratação independente dos módulos;
- idempotência de mensagens e documentos;
- PostgreSQL + Alembic para homologação;
- armazenamento persistente de mídia em Supabase Storage;
- Blueprint Render e readiness real.

## Executar localmente

```bash
python -m pip install -e '.[dev]'
alembic upgrade head
pytest
uvicorn app.main:app --reload
```

Por padrão, desenvolvimento local pode usar SQLite e filesystem. Homologação usa PostgreSQL/Supabase e storage privado.

Endpoints principais:

- `GET /health`
- `GET /ready`
- `GET /v1/me`
- `POST /v1/operator/messages`
- `POST /v1/operator/media/invoice`
- `POST /v1/operator/media/audio`
- `GET /v1/manager/pending`
- webhooks em `/v1/channels/webhooks/...`

## Homologação

A Base 06 está documentada em [`docs/BASE06_STAGING.md`](docs/BASE06_STAGING.md).

O módulo Pecuária já faz parte do catálogo modular e do controle de acesso, mas os fluxos pecuários do novo núcleo ainda precisam ser implementados/homologados antes de operação real.
