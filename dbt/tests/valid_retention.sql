select * from {{ ref('customer_cohorts') }} where retention_rate < 0 or retention_rate > 1
