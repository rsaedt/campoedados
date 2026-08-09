# Fluxos de homologação — primeira fatia

## 1. Produção

Mensagem: `Fiz 3 batidas da Seca 0,1`.

A fórmula de teste usa, por batida, 350 kg de milho, 50 kg de farelo de soja, 35 kg de ureia, 40 kg de sal branco e 25 kg de núcleo, totalizando 500 kg.

Para 3 batidas:

- milho: -1.050 kg;
- farelo: -150 kg;
- ureia: -105 kg;
- sal: -120 kg;
- núcleo: -75 kg;
- Seca 0,1: +1.500 kg.

Custo bruto aproximado = soma de `quantidade consumida × custo médio vigente` de cada ingrediente.

## 2. Transferência

Mensagem: `Carreguei 80 sacos para NSG`.

A transferência conserva o custo do produto na origem. Na expedição, quantidade e valor saem da origem e ficam representados pela transferência em trânsito. No recebimento, a mesma quantidade e o mesmo custo entram no destino.

Transferência interna não gera compra, venda, receita ou despesa.

## 3. Compra / NF

Mensagem: `Chegou milho, segue NF`.

A entrada física pode alimentar a Fábrica de Ração. Quando o módulo Financeiro estiver habilitado, a mesma ocorrência pode gerar compra e parcelas de contas a pagar.

A compra nasce aguardando aprovação gerencial. As parcelas também ficam pendentes até a aprovação; após aprovação passam para abertas.

O contas a pagar pertence à Agropecuária/organização. SH7 e NSG podem aparecer como destino físico e/ou centro de custo, sem criar contas a pagar separados por fazenda.
