"""LLM narrator — generates goal-driven persona conversation."""

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

    def generate_message(
        self, goal: str, conversation: list[dict], turn: int,
    ) -> str:
        """Generate what the persona would type next, driven by goal and history."""
        p = self.persona
        prompt = (
            f"You are roleplaying as {p['name']}, a {p['title']} "
            f"at {p['company']} on the {p['team']} team.\n\n"
            f"ROLE IN OPPORTUNITY LIFECYCLE:\n{p['lifecycle_role']}\n\n"
            f"COMMUNICATION STYLE:\n{p['communication_style']}\n\n"
            f"Expertise: {', '.join(p['expertise'])}\n"
            f"Agencies tracked: {', '.join(p['agencies_of_interest'])}\n"
            f"Systems used: {', '.join(p.get('systems_used', []))}\n\n"
            f"YOUR GOAL FOR THIS SESSION:\n{goal}\n\n"
        )

        if conversation:
            prompt += "CONVERSATION SO FAR:\n"
            for msg in conversation[-6:]:  # last 3 exchanges max
                role = "You" if msg["role"] == "user" else "Assistant"
                text = msg["content"][:500]
                prompt += f"{role}: {text}\n\n"

        if turn == 1:
            prompt += "This is your FIRST message. Start the conversation naturally.\n\n"
        else:
            prompt += (
                "Based on what you've learned so far, what would you ask or say next?\n"
                "If the assistant gave you useful info, dig deeper or ask a follow-up.\n"
                "If something was wrong or missing, push back or redirect.\n"
                "If you got what you need, ask for a summary or shift to a related need.\n\n"
            )

        prompt += (
            "Generate ONLY the message you would type into the chat box.\n"
            "Be natural, specific, 1-3 sentences. Use business language, not tech jargon.\n"
            "Never mention tools, APIs, MCP, or system internals."
        )

        return self._chat(prompt, max_tokens=250)

    def should_continue(
        self, goal: str, conversation: list[dict], turn: int, max_turns: int,
    ) -> bool:
        """Decide if the persona has gotten what they need or should keep going."""
        if turn >= max_turns:
            return False
        if turn < 2:
            return True  # always do at least 2 turns

        prompt = (
            f"You are {self.persona['name']}, a {self.persona['title']}.\n"
            f"Your goal: {goal}\n\n"
            f"You've had {turn} exchanges. Here's the latest assistant response:\n"
            f"{conversation[-1]['content'][:1000]}\n\n"
            "Have you gotten enough useful information to accomplish your goal, "
            "or do you need to ask more questions?\n\n"
            "Reply with exactly one word: CONTINUE or DONE"
        )

        result = self._chat(prompt, max_tokens=10).strip().upper()
        return "CONTINUE" in result

    def generate_reaction(
        self, goal: str, user_message: str, assistant_response: str,
    ) -> str:
        """Generate persona's internal reaction (for report, not sent to chat)."""
        p = self.persona
        prompt = (
            f"You are {p['name']}, a {p['title']}.\n"
            f"Your goal: {goal}\n"
            f"You just asked: \"{user_message}\"\n"
            f"The assistant responded with:\n{assistant_response[:1500]}\n\n"
            f"Write 1-2 sentences of your internal reaction. Are you satisfied? "
            f"Confused? Impressed? Frustrated? What would you do next?\n"
            f"Stay in character."
        )

        return self._chat(prompt, max_tokens=150)

    def close(self) -> None:
        self.client.close()
