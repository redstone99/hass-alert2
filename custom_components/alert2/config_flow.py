"""Config flow for the Alert2 component."""
import secrets

from homeassistant import config_entries
from . import DOMAIN

class Alert2ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Alert2."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""

        # Only a single instance of the integration
        if self._async_current_entries():
            return self.async_abort(reason="Only single entry allowed")

        id = secrets.token_hex(6)

        await self.async_set_unique_id(id)
        self._abort_if_unique_id_configured(updates=user_input)

        return self.async_create_entry(title="Alert2", data={})
    
