"""LLM narrator — generates persona voice and reactions via OpenAI-compatible API."""

import httpx


class Narrator:
    def __init__(self, base_url: str, api_key: str, model: str, persona: dict):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.persona = persona
        self.client = httpx.Client()

    def _chat(self, prompt: str, max_tokens: int = 200) -> str:
        """Send a chat completion request to the LLM proxy."""
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def generate_user_message(
        self, beat: dict, previous_response: str | None
    ) -> str:
        """Generate what the persona would type for this conversation beat."""
        p = self.persona
        prompt = (
            f"You are roleplaying as {p['name']}, a {p['title']} "
            f"at {p['company']} on the {p['team']} team.\n\n"
            f"{p['communication_style']}\n\n"
            f"Expertise: {', '.join(p['expertise'])}\n"
            f"Agencies tracked: {', '.join(p['agencies_of_interest'])}\n\n"
            f"CURRENT TASK BEAT:\n"
            f"- Intent: {beat['intent']}\n"
            f"- Context: {beat['context']}\n\n"
        )
        if previous_response:
            prompt += f"PREVIOUS ASSISTANT RESPONSE:\n{previous_response}\n\n"
        else:
            prompt += "This is the START of the conversation.\n\n"

        prompt += (
            "Generate ONLY the message this person would type into the chat box.\n"
            "Be natural, specific, 1-3 sentences. Use business language, not tech jargon.\n"
            "Never mention tools, APIs, MCP, or system internals."
        )

        return self._chat(prompt, max_tokens=200)

    def generate_reaction(
        self, beat: dict, user_message: str, assistant_response: str
    ) -> str:
        """Generate persona's internal reaction (for report, not sent to chat)."""
        p = self.persona
        prompt = (
            f"You are {p['name']}, a {p['title']}.\n"
            f"You just asked: \"{user_message}\"\n"
            f"The assistant responded with:\n{assistant_response[:1500]}\n\n"
            f"Write 1-2 sentences of your internal reaction. Are you satisfied? "
            f"Confused? Impressed? Frustrated? What would you do next?\n"
            f"Stay in character as a BD professional."
        )

        return self._chat(prompt, max_tokens=150)

    def assess_beat(
        self, beat: dict, assistant_response: str
    ) -> dict:
        """Assess whether a beat's success signal was met."""
        success_signal = beat.get("success_signal", "")
        if not success_signal:
            return {"met": True, "reason": "No success signal defined"}

        prompt = (
            f"A user asked an AI assistant about: \"{beat['intent']}\"\n\n"
            f"The assistant responded:\n{assistant_response[:1500]}\n\n"
            f"SUCCESS SIGNAL: {success_signal}\n\n"
            f"Was the success signal met? Reply with exactly one line:\n"
            f"MET: <brief reason>\n"
            f"or\n"
            f"NOT MET: <brief reason>"
        )

        text = self._chat(prompt, max_tokens=100).strip()
        met = text.upper().startswith("MET")
        return {"met": met, "reason": text}

    def close(self) -> None:
        self.client.close()
