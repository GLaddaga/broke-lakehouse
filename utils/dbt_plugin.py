"""
The lakehouse, attached to dbt-duckdb's connection by `attach()` itself.

Architectural choice details @docs/transformation.md
"""

from dbt.adapters.duckdb.plugins import BasePlugin

from utils.lakehouse import attach


class Plugin(BasePlugin):
    def initialize(self, plugin_config):
        self.environment = plugin_config["environment"]

    def configure_connection(self, conn):
        attach(self.environment, con=conn)
