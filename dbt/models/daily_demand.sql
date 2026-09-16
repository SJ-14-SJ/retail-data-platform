-- A dense calendar is deliberate: zero units means no recorded sale, not missing capture.
with bounds as (
    select min(cast(order_date as date)) as first_day, max(cast(order_date as date)) as last_day
    from {{ source('retail', 'order_lines') }}
), calendar as (
    select generate_series(first_day, last_day, interval '1 day')::date as order_date
    from bounds
), skus as (
    select distinct sku from {{ ref('stg_sales') }}
), daily as (
    select sku, order_date, sum(quantity) as units, sum(revenue_cents) as revenue_cents
    from {{ ref('stg_sales') }} group by sku, order_date
)
select s.sku, c.order_date,
       coalesce(d.units, 0) as units,
       coalesce(d.revenue_cents, 0) as revenue_cents
from skus s cross join calendar c
left join daily d on d.sku = s.sku and d.order_date = c.order_date
