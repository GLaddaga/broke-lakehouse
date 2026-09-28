-- One row per customer, with the geography sales reports by already joined on.
select
    c.customer_key,
    c.name,
    c.market_segment,
    n.name as nation,
    r.name as region
from {{ ref('customer__tpch') }} c
join {{ ref('nation__tpch') }} n using (nation_key)
join {{ ref('region__tpch') }} r using (region_key)
