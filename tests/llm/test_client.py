from llm.client import ChatMessage, DEFAULT_LLM_MAX_OUTPUT_TOKENS, LLMClient, LLMError


def test_chat_message_fields():
    msg = ChatMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_llm_client_is_protocol_runtime_checkable():
    class StubClient:
        def chat_json(
            self,
            system,
            user,
            json_schema,
            max_tokens=DEFAULT_LLM_MAX_OUTPUT_TOKENS,
            model=None,
        ):
            return {}

    assert isinstance(StubClient(), LLMClient)


def test_default_llm_output_budget_is_16k():
    assert DEFAULT_LLM_MAX_OUTPUT_TOKENS == 16000


def test_llm_client_rejects_non_conforming():
    class NotAClient:
        def send(self, x):
            return x

    assert not isinstance(NotAClient(), LLMClient)


def test_llm_error_is_exception():
    err = LLMError("boom")
    assert isinstance(err, Exception)
    assert str(err) == "boom"
