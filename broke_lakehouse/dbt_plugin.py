"""
The lakehouse's credentials, on dbt-duckdb's connection, so that the
`attach:` entry in `profiles.yml` can attach it.

Architectural choice details @docs/transformation.md
"""

from dbt.adapters.duckdb.plugins import BasePlugin

from broke_lakehouse.client import attach, credentials


class Plugin(BasePlugin):
    def initialize(self, plugin_config):
        self.environment = plugin_config["environment"]
        # The initialised-catalog guard, on a throwaway connection as in destination():
        # dbt's own attach comes after the plugin, where no hook can check it.
        attach(self.environment).close()

    def configure_connection(self, conn):
        credentials(self.environment, conn)
