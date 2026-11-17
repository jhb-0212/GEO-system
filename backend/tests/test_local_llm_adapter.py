"""本地 OpenAI 兼容适配器单测：只测协议归一与失败归类，不依赖真实 Ollama。"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    EngineProtocol,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.local_llm_adapter import LocalLLMAdapter
from app.services.monitoring_collection import AccessBlockedFailure, RateLimitedFailure, build_entry_adapter
from app.services.openai_compatible_adapter import OpenAICompatibleAdapter


def _make_task(db, project) -> MonitoringTask:
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title="广州基地的课程怎么报名？",
        question_type=QuestionType.BRAND,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text=question.title,
    )
    db.add(version)
    engine = AiEngine(
        code=f"local-{uuid.uuid4().hex[:6]}",
        name="本地 Ollama",
        vendor="Local",
        supports_search=False,
        supports_citation=False,
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.API,
        name="本地 API",
        entry_url="http://127.0.0.1:11434/v1",
    )
    db.add(entry)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="本地 smoke",
        is_baseline=True,
        status=RoundStatus.RUNNING,
    )
    db.add(round_row)
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    return task


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_local_adapter_normalizes_openai_response(db, project_factory):
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b",
                "choices": [{"message": {"content": "广州基地可以通过官网咨询报名。"}}],
            },
        )

    with _mock_client(handler) as client:
        adapter = LocalLLMAdapter(
            db,
            base_url="http://local.test/v1",
            model="qwen2.5:7b",
            client=client,
        )
        payload = adapter.collect(task)

    assert seen["url"] == "http://local.test/v1/chat/completions"
    assert seen["body"]["model"] == "qwen2.5:7b"
    assert seen["body"]["stream"] is False
    assert payload.text == "广州基地可以通过官网咨询报名。"
    assert payload.engine_model == "qwen2.5:7b"
    assert payload.model_version == "qwen2.5:7b"
    assert payload.country_code == "CN"
    assert payload.language == "zh"


def test_local_adapter_preserves_optional_citations(db, project_factory):
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b",
                "choices": [{"message": {"content": "广州基地官网是 gz-base.com。"}}],
                "sources": [{"url": "https://gz-base.com"}],
            },
        )

    with _mock_client(handler) as client:
        adapter = LocalLLMAdapter(
            db,
            base_url="http://local.test/v1",
            model="qwen2.5:7b",
            client=client,
        )
        payload = adapter.collect(task)

    assert len(payload.citations) == 1
    assert payload.citations[0].url == "https://gz-base.com"


def test_local_adapter_classifies_429(db, project_factory):
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with _mock_client(handler) as client:
        adapter = LocalLLMAdapter(
            db,
            base_url="http://local.test/v1",
            model="qwen2.5:7b",
            client=client,
        )
        with pytest.raises(RateLimitedFailure):
            adapter.collect(task)


def test_local_adapter_classifies_unreachable(db, project_factory):
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with _mock_client(handler) as client:
        adapter = LocalLLMAdapter(
            db,
            base_url="http://local.test/v1",
            model="qwen2.5:7b",
            client=client,
        )
        with pytest.raises(AccessBlockedFailure):
            adapter.collect(task)


def test_openai_compatible_adapter_adds_qianfan_web_search(db, project_factory):
    """千帆 ERNIE 对话模型入口：联网开关必须进入请求体顶层。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "ernie-5.1",
                "choices": [{"message": {"content": "广州今天多云。"}}],
            },
        )

    with _mock_client(handler) as client:
        adapter = OpenAICompatibleAdapter(
            db,
            base_url="https://qianfan.baidubce.com/v2",
            model="ernie-5.1",
            client=client,
            enable_web_search=True,
        )
        payload = adapter.collect(task)

    assert seen["url"] == "https://qianfan.baidubce.com/v2/chat/completions"
    assert seen["body"]["web_search"] == {"enable": True}
    assert seen["body"]["model"] == "ernie-5.1"
    assert payload.text == "广州今天多云。"


def test_build_entry_adapter_enables_qianfan_search_only_when_entry_supports_search(
    db, project_factory
):
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = "https://qianfan.baidubce.com/v2"
    entry.model_name = "ernie-5.1"
    entry.credential_ref = None
    entry.supports_search = True
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.enable_web_search is True
