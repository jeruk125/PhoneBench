import requests


class AIProviderError(RuntimeError):
    pass


class AIProvider:
    def generate(self, prompt, evidence):
        raise NotImplementedError


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, base_url, api_key, model, temperature=0.2, max_tokens=600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt, evidence):
        if not self.base_url or not self.api_key or not self.model:
            raise AIProviderError("AI is not configured. Set a base URL, API key, and model in Settings.")
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "messages": [
                        {"role": "system", "content": "Use only the supplied PhoneBench evidence for repair facts. Do not invent procedures. Separate evidence from interpretation and warn that history is not a guarantee."},
                        {"role": "user", "content": f"PhoneBench evidence:\n{evidence}\n\nQuestion:\n{prompt}"},
                    ],
                },
                timeout=45,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            raise AIProviderError(f"AI provider request failed: {exc}") from exc
