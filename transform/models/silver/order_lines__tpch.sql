-- One row per order line, carrying its order's customer and date.
-- Net revenue is TPC-H's own definition: price after discount, before tax.
select
    l.order_key,
    l.line_number,
    o.customer_key,
    o.order_date,
    o.status as order_status,
    l.quantity,
    l.extended_price * (1 - l.discount) as net_revenue,
    l.return_flag
from {{ ref('lineitem__tpch') }} l
join {{ ref('orders__tpch') }} o using (order_key)
