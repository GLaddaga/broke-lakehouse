{#- The layer's name as-is. dbt's default prefixes it with the target schema
    (`main_bronze`), and names are identical in every environment. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name or target.schema }}
{%- endmacro %}
