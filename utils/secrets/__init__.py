"""The secret manager in use. Callers import `get_secrets` from here, never from
a provider module, so swapping provider is this one import. @docs/secrets.md"""

from utils.secrets.infisical import get_secrets
