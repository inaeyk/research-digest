from __future__ import annotations

import inspect
import socket
import unittest
from typing import Any, cast
from unittest import mock

from research_digest.analysis.openai import OpenAIAbstractPreselector, OpenAIAnalyzer
from research_digest.conversation_providers import OpenAIResearchConversationProvider
from research_digest.summary_providers import OpenAILibrarySummaryProvider


class OpenAIFloorCompatibilityTests(unittest.TestCase):
    def test_production_adapters_construct_without_network_and_expose_responses_shape(
        self,
    ) -> None:
        with mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("adapter construction attempted network access"),
        ) as network:
            library = OpenAILibrarySummaryProvider(
                api_key="sk-offline-construction-only",
                model="floor-shape-model",
            )
            conversation = OpenAIResearchConversationProvider(
                api_key="sk-offline-construction-only",
                model="floor-shape-model",
                timeout_seconds=17,
            )
            analyzer = OpenAIAnalyzer(
                api_key="sk-offline-construction-only",
                model="floor-shape-model",
            )
            preselector = OpenAIAbstractPreselector(
                api_key="sk-offline-construction-only",
                model="floor-shape-model",
            )

        network.assert_not_called()
        for adapter in (library, conversation, analyzer, preselector):
            client = cast(Any, adapter)._client
            parameters = inspect.signature(client.responses.create).parameters
            self.assertTrue({"model", "input", "text", "timeout"} <= parameters.keys())
            inspect.signature(client.responses.create).bind_partial(
                model="floor-shape-model",
                input=[{"role": "user", "content": "offline shape only"}],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "offline_shape",
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["value"],
                            "properties": {"value": {"type": "string"}},
                        },
                        "strict": True,
                    }
                },
            )

        conversation_client = cast(Any, conversation)._client
        self.assertEqual(conversation_client.max_retries, 0)
        self.assertEqual(conversation_client.timeout, 17)


if __name__ == "__main__":
    unittest.main()
