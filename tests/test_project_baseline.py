def test_pocketflow_is_importable() -> None:
    import pocketflow

    assert pocketflow.Node is not None


def test_paperclaw_version() -> None:
    import paperclaw

    assert paperclaw.__version__ == "0.0.1"
