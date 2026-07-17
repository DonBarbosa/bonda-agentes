# Odoo + Mercado Libre disponíveis para Grecia no Claude Team

Estado da tarefa e passo-a-passo para concluir. Verificado em **2026-07-17**.

---

## TL;DR

- **Backend (Make): pronto e verde.** Odoo e Mercado Libre respondem ao vivo
  (HTTP 200) através do conector MCP do Make. Nada quebrado.
- **Único bloqueio restante:** adicionar/habilitar esse conector no **seat da
  Grecia** no Claude Team. É ação de UI (admin do Team ou a própria Grecia) —
  não dá para fazer via API.

---

## O que está exposto hoje como ferramenta MCP

Org Make: **Bonda Alimentos** · Team `My Team` (985684) · zona `eu1`.

### Mercado Libre — 15 tools (todas ON, `ML_LIVE`, seller BONDA ALIMENTOS / MLM)

| Tool | Função |
|---|---|
| `ml_account_health` | Saúde da conta / seller_id |
| `ml_list_items` | Lista de anúncios |
| `ml_get_item` / `ml_get_orders` / `ml_get_order` | Item / pedidos / pedido |
| `ml_get_shipment` / `ml_pedido_envio` | Envio |
| `ml_get_questions` / `ml_preguntas_pendientes` | Perguntas |
| `ml_get_claims` / `ml_reclamos_abiertos` | Reclamações |
| `ml_get_promotions` / `ml_get_notifications_status` | Promoções / notificações |
| `ml_prices_batch_2` / `ml_prices_batch_3` | Preços em lote |

### Odoo — 5 tools (conexão `BONDA Odoo sanos3` #7361751, todas read-only, HTTP 200)

| Tool | Função |
|---|---|
| `odoo_buscar_cliente` | Cliente por nome (res.partner) |
| `odoo_buscar_producto` | Produto por SKU/nome — inclui **custo, estoque, preço, imposto** |
| `odoo_buscar_por_ref` | Cotização/pedido (sale.order) por `client_order_ref` exato |
| `odoo_status_pedido` | **NOVO (17/07)** — status de pedido de venta (sale.order): cliente, estado, total, data, entrega prometida |
| `odoo_rastreabilidade_lote` | **NOVO (17/07)** — lote (stock.lot): produto, quantidade on-hand, data. Uso LAB/PEPS |

> `odoo_buscar_producto` já devolve custo + estoque num só tool — por isso os
> antigos scenarios "Custo Produto" e "Estoque Tempo Real" (OFF) não precisam
> ser expostos separadamente.
>
> Nota técnica (lote): o Odoo desta conta (saas-19.2) **não tem o módulo
> `product_expiry`**, então `stock.lot` não expõe `expiration_date`/`use_date`.
> O `odoo_rastreabilidade_lote` usa só campos garantidos (name, product_id,
> product_qty, create_date). Se instalarem `product_expiry`, dá pra acrescentar
> validade num minuto.

---

## Passo que falta: habilitar o conector no Claude Team da Grecia

O conector MCP do Make já funciona (esta sessão o usa). Falta só ele aparecer
no seat da Grecia. Escolha **um** caminho:

### Caminho A — Conector da organização (recomendado no plano Team)

Feito pelo Roger (admin do Team):

1. Claude Team → **Settings → Connectors** (Conectores da organização).
2. Se o conector do Make já estiver listado como conector da org: **habilite-o
   para a Grecia** (ou para toda a org).
3. Se ainda for conector *pessoal* do Roger: **Add custom connector** →
   cole a URL MCP do Make (ver abaixo) → habilite para os membros.
4. A Grecia entra no chat dela → ícone de conectores → liga o do Make.

### Caminho B — Conector pessoal da Grecia

1. Grecia: **Settings → Connectors → Add custom connector**.
2. Cola a mesma URL MCP do Make.
3. Liga o conector no chat.

### Onde pegar a URL MCP do Make

No Make (conta do Roger, dona dos scenarios): **Profile → MCP token** (ou
seção MCP/API). Copie a URL exibida — formato:

```
https://eu1.make.com/mcp/api/v1/u/<TOKEN>/sse
```

Essa URL expõe automaticamente **todos os scenarios on-demand** da conta —
hoje são exatamente os 15 ML + 5 Odoo acima (20 tools). Os scenarios de escrita
(ex.: criar cotação/draft) estão **OFF**, então o conector é read-only por ora.

> Segurança: essa URL contém um token com acesso aos tools da conta do Roger.
> Compartilhe só com a Grecia. Para revogar depois, regenere o token no Make.

---

## Checklist para "concluído"

- [x] Odoo ao vivo (200) — 5 tools read-only
- [x] Mercado Libre ao vivo (200) — 15 tools
- [x] `odoo_status_pedido` criado, ativado e testado
- [x] `odoo_rastreabilidade_lote` criado, ativado e testado
- [ ] Conector do Make habilitado no seat da Grecia (Caminho A ou B) — **Roger/Grecia**
- [ ] Grecia confirma que vê os tools no chat dela

Tudo que dependia de mim (lado Make) está feito e verde. O único item aberto é
a ação de UI no Claude Team — que só o admin (Roger) ou a Grecia conseguem fazer.
