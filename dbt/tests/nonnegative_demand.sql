select * from {{ ref('daily_demand') }} where units < 0 or revenue_cents < 0
