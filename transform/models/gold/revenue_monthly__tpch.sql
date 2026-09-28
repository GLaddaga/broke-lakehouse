-- The sales question: which regions and market segments bring in the revenue,
-- month by month. One row per month × region × segment.
select
    date_trunc('month', ol.order_date)::date as month,
    c.region,
    c.market_segment,
    sum(ol.net_revenue)                      as net_revenue,
    count(distinct ol.order_key)             as orders,
    count(distinct ol.customer_key)          as customers
from {{ ref('order_lines__tpch') }} ol
join {{ ref('customers__tpch') }} c using (customer_key)
group by all
