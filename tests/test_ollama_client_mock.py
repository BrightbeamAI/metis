from tacitflow.models.model_config import ModelConfig
from tacitflow.models.ollama_client import OllamaClient
from tacitflow.models.structured_outputs import AssistPurpose


def test_client_unavailable_in_deterministic_mode():
    client = OllamaClient(ModelConfig(), deterministic=True)
    assert client.available() is False


def test_client_fails_gracefully_when_server_absent():
    # Point at a definitely-dead endpoint; must not raise, must fall back.
    cfg = ModelConfig(url="http://127.0.0.1:1")
    client = OllamaClient(cfg, deterministic=False)
    assert client.available() is False
    res = client.run(AssistPurpose.classify_fragment, "operator heard a dull acoustic cue")
    assert res.used_live_model is False
    assert "category" in res.json()


def test_mocked_responder_used_without_network():
    client = OllamaClient(ModelConfig(), deterministic=False,
                          responder=lambda purpose, prompt: '{"summary": "mocked"}')
    res = client.run(AssistPurpose.summarise_confirmation, "anything")
    assert res.json()["summary"] == "mocked"
    assert res.used_live_model is False


def test_deterministic_classification_is_stable():
    client = OllamaClient(ModelConfig(), deterministic=True)
    a = client.run(AssistPurpose.classify_fragment, "low-frequency vibration and a dull acoustic cue")
    b = client.run(AssistPurpose.classify_fragment, "low-frequency vibration and a dull acoustic cue")
    assert a.json() == b.json()
