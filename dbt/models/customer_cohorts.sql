with customer_months as (
    select distinct customer_id, date_trunc('month', order_date)::date as activity_month
    from {{ ref('stg_sales') }} where customer_id != 'unknown'
), first_purchase as (
    select customer_id, min(activity_month) as cohort_month
    from customer_months group by customer_id
), cohort_counts as (
    select f.cohort_month, m.activity_month, count(*) as active_customers
    from customer_months m join first_purchase f using (customer_id)
    group by f.cohort_month, m.activity_month
)
select cohort_month, activity_month, active_customers,
       1.0 * active_customers / nullif(first_value(active_customers) over (
           partition by cohort_month order by activity_month
       ), 0) as retention_rate
from cohort_counts
