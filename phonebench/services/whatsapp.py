import requests


class WhatsAppProviderError(RuntimeError):
    pass


class WhatsAppProvider:
    def send_message(self, phone, message):
        raise NotImplementedError


class CloudAPIProvider(WhatsAppProvider):
    def __init__(self, access_token, phone_number_id, api_version="v22.0"):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = api_version

    def send_message(self, phone, message):
        if not self.access_token or not self.phone_number_id:
            raise WhatsAppProviderError("WhatsApp Cloud API is not configured.")
        try:
            response = requests.post(
                f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages",
                headers={"Authorization": f"Bearer {self.access_token}"},
                json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": message}},
                timeout=20,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise WhatsAppProviderError(f"WhatsApp provider request failed: {exc}") from exc
