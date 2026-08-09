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
- auditoria.

## Regras implementadas nesta base

1. Uma organização pode habilitar qualquer combinação de módulos.
2. Produção de ração baixa ingredientes e calcula custo bruto aproximado pela soma dos custos dos produtos consumidos.
3. O produto fabricado entra no estoque com custo unitário calculado.
4. Transferência entre unidades leva quantidade **e valor**, sem criar compra, venda, receita ou despesa.
5. O contas a pagar pertence à **organização/Agropecuária**, podendo ser alocado a centros de custo/unidades.

## Executar

```bash
python -m pip install -e '.[dev]'
pytest
uvicorn app.main:app --reload
```

Endpoints iniciais:

- `GET /health`
- `GET /ready`

Esta primeira base deliberadamente não expõe endpoints de escrita sem autenticação. A API operacional será adicionada junto com autenticação/autorização.
