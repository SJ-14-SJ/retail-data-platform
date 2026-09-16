select line_id, order_id, sku, customer_id,
       cast(order_date as date) as order_date,
       quantity, unit_price_cents,
       cast(quantity as bigint) * unit_price_cents as revenue_cents
from {{ source('retail', 'order_lines') }}
where status = 'sale'
