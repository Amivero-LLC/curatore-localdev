"""Abstract transport interface."""

from abc import ABC, abstractmethod


class BaseTransport(ABC):
    @abstractmethod
    async def send_message(self, message: str) -> dict:
        """Send a user message and return the assistant response.

        Returns:
            dict with keys: content (str), model (str|None),
            usage (dict|None), raw (dict)
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset conversation state (start fresh for new task)."""
