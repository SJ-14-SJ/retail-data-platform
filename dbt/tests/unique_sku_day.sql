select sku, order_date, count(*) as records
from {{ ref('daily_demand') }} group by sku, order_date having count(*) > 1
