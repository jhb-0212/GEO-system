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
    AnswerKind,
    EngineEntryType,
    EngineProtocol,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.kimi_web_search_adapter import KimiWebSearchAdapter
from app.services.local_llm_adapter import LocalLLMAdapter
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    build_entry_adapter,
)
from app.services.openai_compatible_adapter import OpenAICompatibleAdapter
from app.services.qihu360_search_adapter import Qihu360SearchAdapter
from app.services.qwen_web_search_adapter import QwenWebSearchAdapter
from app.services.zhipu_search_adapter import ZhipuModelSearchAdapter


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


def test_openai_compatible_adapter_adds_qwen_web_search_and_citations(db, project_factory):
    """千问 Chat 兼容模式：只用于历史适配器，系统联网采集已切 Responses。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "qwen3.8-max",
                "choices": [{"message": {"content": "广州基地今年开放了新课程。"}}],
                "search_info": {
                    "search_results": [
                        {
                            "index": 1,
                            "title": "广州基地课程介绍",
                            "url": "https://gz-base.example/courses",
                            "site_name": "gz-base.example",
                        },
                        {
                            "index": 2,
                            "title": "报名入口",
                            "url": "https://gz-base.example/signup",
                            "site_name": "gz-base.example",
                        },
                    ]
                },
            },
        )

    with _mock_client(handler) as client:
        adapter = OpenAICompatibleAdapter(
            db,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.8-max",
            client=client,
            web_search_mode="qwen",
        )
        payload = adapter.collect(task)

    assert seen["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert seen["body"]["enable_search"] is True
    assert seen["body"]["search_options"] == {
        "enable_source": True,
        "enable_citation": True,
    }
    assert payload.text == "广州基地今年开放了新课程。"
    assert [citation.url for citation in payload.citations] == [
        "https://gz-base.example/courses",
        "https://gz-base.example/signup",
    ]
    assert payload.answer_kind == AnswerKind.ANSWER


def test_openai_compatible_adapter_adds_spark_web_search(db, project_factory):
    """星辰 MaaS：用 max_completion_tokens，并把联网声明放进 tools。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "code": 0,
                "model": "spark-x2.6",
                "choices": [{"message": {"content": "广州今天多云。"}}],
            },
        )

    with _mock_client(handler) as client:
        adapter = OpenAICompatibleAdapter(
            db,
            base_url="https://maas-api.cn-huabei-1.xf-yun.com/v2",
            model="spark-x2.6",
            client=client,
            web_search_mode="spark",
        )
        payload = adapter.collect(task)

    assert seen["url"] == "https://maas-api.cn-huabei-1.xf-yun.com/v2/chat/completions"
    body = seen["body"]
    assert body["max_completion_tokens"] == 1024
    assert "max_tokens" not in body
    assert "temperature" not in body
    assert body["thinking"] == {"type": "disabled"}
    assert body["tools"] == [
        {"type": "web_search", "web_search": {"enable": True}}
    ]
    assert body["tool_choice"] == "auto"
    assert payload.text == "广州今天多云。"
    assert payload.answer_kind == AnswerKind.ANSWER
    assert payload.citations == []


def test_openai_compatible_adapter_keeps_spark_tools_off_when_search_disabled(
    db, project_factory
):
    """未开启 supports_search 时仍按 Spark 参数发送，但不带 web_search 工具。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "code": 0,
                "model": "spark-x2.6",
                "choices": [{"message": {"content": "普通回答。"}}],
            },
        )

    with _mock_client(handler) as client:
        adapter = OpenAICompatibleAdapter(
            db,
            base_url="https://maas-api.cn-huabei-1.xf-yun.com/v2",
            model="spark-x2.6",
            client=client,
        )
        adapter.collect(task)

    assert seen["body"]["max_completion_tokens"] == 1024
    assert "tools" not in seen["body"]
    assert "temperature" not in seen["body"]


def test_build_entry_adapter_selects_spark_web_search(db, project_factory, monkeypatch):
    """SPARK_API_KEY 存在且 supports_search=true 时，选 Spark 联网模式。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
    entry.model_name = "spark-x2.6"
    entry.credential_ref = "SPARK_API_KEY"
    entry.supports_search = True
    monkeypatch.setenv("SPARK_API_KEY", "spark-example")
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.web_search_mode == "spark"
    assert adapter.enable_web_search is True


def test_zhipu_search_adapter_uses_configured_model(db, project_factory):
    """智谱两段式：独立 Web Search 取来源，再用入口配置的任意模型回答。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content.decode("utf-8"))
        seen.append({"path": path, "body": body})
        if path.endswith("/web_search"):
            return httpx.Response(
                200,
                json={
                    "search_result": [
                        {
                            "title": "广州人工智能新闻",
                            "link": "https://example.com/ai-news",
                            "media": "示例网",
                            "publish_date": "2026-11-20",
                            "content": "广州人工智能相关活动报道。",
                            "refer": "ref_1",
                        },
                        {
                            "title": "重复来源",
                            "link": "https://example.com/ai-news",
                            "media": "示例网",
                            "publish_date": "2026-11-20",
                            "content": "重复链接。",
                            "refer": "ref_2",
                        },
                    ]
                },
            )
        if path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [
                        {
                            "message": {
                                "content": "广州今天有人工智能相关新闻，来源见引用。",
                                "role": "assistant",
                            }
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    with _mock_client(handler) as client:
        adapter = ZhipuModelSearchAdapter(
            db,
            base_url="https://open.bigmodel.cn/api/paas/v4",
            model="glm-5.3-flashx",
            api_key="zhipu-example",
            client=client,
        )
        payload = adapter.collect(task)

    search_req = next(item for item in seen if item["path"].endswith("/web_search"))
    chat_req = next(item for item in seen if item["path"].endswith("/chat/completions"))
    assert search_req["body"]["search_query"] == "广州基地的课程怎么报名？"
    assert search_req["body"]["search_engine"] == "search_pro"
    assert "search_result" not in search_req["body"]
    assert "tools" not in chat_req["body"]
    assert chat_req["body"]["model"] == "glm-5.3-flashx"
    assert "广州人工智能新闻" in chat_req["body"]["messages"][1]["content"]
    assert payload.text == "广州今天有人工智能相关新闻，来源见引用。"
    assert payload.answer_kind == AnswerKind.ANSWER
    assert len(payload.citations) == 1
    citation = payload.citations[0]
    assert citation.url == "https://example.com/ai-news"
    assert citation.title == "广州人工智能新闻"
    assert citation.site_name == "示例网"
    assert citation.snippet == "广州人工智能相关活动报道。"
    assert citation.published_at is not None
    assert citation.published_at.date().isoformat() == "2026-11-20"


def test_zhipu_search_adapter_stops_on_search_balance_error(db, project_factory):
    """搜索余额不足时在第一步失败，不再调模型，避免把模型额度当搜索额度。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            429,
            json={"error": {"code": "1113", "message": "余额不足或无可用资源包,请充值。"}},
        )

    with _mock_client(handler) as client:
        adapter = ZhipuModelSearchAdapter(
            db,
            base_url="https://api.z.ai/api/paas/v4",
            model="glm-5.3-flashx",
            api_key="zhipu-example",
            client=client,
        )
        with pytest.raises(AccessBlockedFailure) as exc:
            adapter.collect(task)

    assert "搜索" in str(exc.value)
    assert paths == ["/api/paas/v4/web_search"]


def test_zhipu_search_adapter_rejects_empty_sources(db, project_factory):
    """搜索返回空来源时拒绝生成无引用回答，也不调模型。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"search_result": []})

    with _mock_client(handler) as client:
        adapter = ZhipuModelSearchAdapter(
            db,
            base_url="https://open.bigmodel.cn/api/paas/v4",
            model="glm-4-flash-250414",
            api_key="zhipu-example",
            client=client,
        )
        with pytest.raises(CollectionFailure) as exc:
            adapter.collect(task)

    assert "来源" in str(exc.value)
    assert paths == ["/api/paas/v4/web_search"]


@pytest.mark.parametrize("host", ["open.bigmodel.cn", "api.z.ai"])
def test_build_entry_adapter_selects_zhipu_search_with_arbitrary_model(
    db, project_factory, monkeypatch, host
):
    """智谱入口不锁定模型：model_name 换成 FlashX 仍选同一两段式适配器。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = f"https://{host}/api/paas/v4"
    entry.model_name = "glm-5.3-flashx"
    entry.credential_ref = "ZHIPU_API_KEY"
    entry.supports_search = True
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-example")
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, ZhipuModelSearchAdapter)
    assert adapter.model == "glm-5.3-flashx"



def test_kimi_web_search_adapter_parses_sources(db, project_factory):
    """Kimi Responses：声明 web_search，并把 action.sources 落成引用。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "model": "kimi-k3",
                "status": "completed",
                "output": [
                    {
                        "type": "web_search_call",
                        "status": "completed",
                        "action": {
                            "type": "search",
                            "query": "广州基地 课程",
                            "sources": [
                                {
                                    "type": "url",
                                    "url": "https://gz-base.example/courses",
                                    "title": "广州基地课程介绍",
                                }
                            ],
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "广州基地提供多门课程，可通过官网报名。",
                            }
                        ],
                    },
                ],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 20,
                    "total_tokens": 140,
                },
            },
        )

    with _mock_client(handler) as client:
        adapter = KimiWebSearchAdapter(
            db,
            api_key="kimi-example",
            model="kimi-k3",
            endpoint="https://api.moonshot.cn/v1/responses",
            client=client,
        )
        payload = adapter.collect(task)

    assert seen["url"] == "https://api.moonshot.cn/v1/responses"
    assert seen["body"]["tools"] == [{"type": "web_search"}]
    assert seen["body"]["include"] == ["web_search_call.action.sources"]
    assert seen["body"]["max_output_tokens"] == 16000
    assert seen["body"]["reasoning_effort"] == "low"
    assert payload.text == "广州基地提供多门课程，可通过官网报名。"
    assert [citation.url for citation in payload.citations] == [
        "https://gz-base.example/courses"
    ]
    assert payload.answer_kind == AnswerKind.ANSWER
    assert payload.prompt_tokens == 120
    assert payload.completion_tokens == 20


def test_qwen_web_search_adapter_parses_sources(db, project_factory):
    """千问 Responses：声明 web_search，并把 action.sources 落成引用。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "resp_qwen_test",
                "model": "qwen3.8-max",
                "status": "completed",
                "output": [
                    {
                        "type": "web_search_call",
                        "status": "completed",
                        "action": {
                            "type": "search",
                            "queries": ["广州 AI 实训基地", "广州 AIGC 课程"],
                            "sources": [
                                {"type": "url", "url": "https://gz-base.example/ai"},
                                {"type": "url", "url": "https://gz-base.example/courses"},
                                {"type": "url", "url": "https://gz-base.example/ai"},
                            ],
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "广州有 AI 实训基地，提供 AIGC 课程。",
                            }
                        ],
                    },
                ],
                "usage": {
                    "input_tokens": 180,
                    "output_tokens": 30,
                    "total_tokens": 210,
                },
            },
        )

    with _mock_client(handler) as client:
        adapter = QwenWebSearchAdapter(
            db,
            api_key="qwen-example",
            model="qwen3.8-max",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/responses",
            client=client,
        )
        payload = adapter.collect(task)

    assert seen["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
    assert seen["body"]["model"] == "qwen3.8-max"
    assert "联网搜索" in seen["body"]["instructions"]
    assert seen["body"]["tools"] == [{"type": "web_search"}]
    assert seen["body"]["max_output_tokens"] == 16000
    assert "include" not in seen["body"]
    assert "reasoning_effort" not in seen["body"]
    assert payload.text == "广州有 AI 实训基地，提供 AIGC 课程。"
    assert [citation.url for citation in payload.citations] == [
        "https://gz-base.example/ai",
        "https://gz-base.example/courses",
    ]
    assert payload.answer_kind == AnswerKind.ANSWER
    assert payload.prompt_tokens == 180
    assert payload.completion_tokens == 30
    assert payload.raw_response["citation_count"] == 2
    assert payload.raw_response["search_actions"][0]["query"] == [
        "广州 AI 实训基地",
        "广州 AIGC 课程",
    ]


def test_qihu360_search_adapter_parses_references_and_corner_markers(db, project_factory):
    """360 智脑 AI 搜索：references 优先，正文角标兜底，按 URL 去重。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "qihu360-test",
                "model": "360gpt-pro",
                "created": 1700000000,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": (
                                "广州有 AI 实训基地。"
                                "[[1](https://gz-base.example/ai)]"
                                "[[2](https://gz-base.example/courses)]"
                                "[[3](https://gz-base.example/apply)]"
                            ),
                        },
                    }
                ],
                "references": [
                    {
                        "rank": 1,
                        "title": "广州 AI 实训基地",
                        "url": "https://gz-base.example/ai",
                        "site_name": "gz-base.example",
                        "summary_ai": "广州 AI 实训基地介绍。",
                        "page_time": "2026-11-20 10:00:00",
                    },
                    {
                        "rank": 2,
                        "title": "AIGC 课程",
                        "url": "https://gz-base.example/courses",
                        "site_name": "gz-base.example",
                        "summary_ai": "课程覆盖 AIGC 工具。",
                        "page_time": "2026-11-20 11:00:00",
                    },
                ],
            },
        )

    with _mock_client(handler) as client:
        adapter = Qihu360SearchAdapter(
            db,
            api_key="qihu-example",
            model="360gpt-pro",
            endpoint="https://api.360.cn/v1/search/aisearch",
            client=client,
        )
        payload = adapter.collect(task)

    assert seen["url"] == "https://api.360.cn/v1/search/aisearch"
    assert seen["body"]["model"] == "360gpt-pro"
    assert seen["body"]["messages"] == [
        {"role": "user", "content": seen["body"]["messages"][0]["content"]}
    ]
    assert seen["body"]["messages"][0]["content"].strip()
    assert seen["body"]["max_refer_search_items"] == 20
    assert seen["body"]["enable_corner_markers"] is True
    assert seen["body"]["enable_web_page_safety"] is True
    assert seen["body"]["search_mode"] == "required"
    assert seen["body"]["stream"] is False
    assert "temperature" not in seen["body"]
    assert "max_tokens" not in seen["body"]
    assert [citation.url for citation in payload.citations] == [
        "https://gz-base.example/ai",
        "https://gz-base.example/courses",
        "https://gz-base.example/apply",
    ]
    assert payload.citations[0].title == "广州 AI 实训基地"
    assert payload.citations[0].site_name == "gz-base.example"
    assert payload.citations[0].snippet == "广州 AI 实训基地介绍。"
    assert payload.citations[0].published_at is not None
    assert payload.answer_kind == AnswerKind.ANSWER
    assert payload.engine_model == "360gpt-pro"
    assert payload.raw_response["citation_count"] == 3


def test_build_entry_adapter_selects_qihu360_ai_search(
    db, project_factory, monkeypatch
):
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = "https://api.360.cn/v1/search"
    entry.model_name = "360gpt-pro"
    entry.credential_ref = "QIHU360_API_KEY"
    entry.supports_search = True
    monkeypatch.setenv("QIHU360_API_KEY", "qihu-example")
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, Qihu360SearchAdapter)
    assert adapter.endpoint == "https://api.360.cn/v1/search/aisearch"


def test_openai_compatible_adapter_parses_metaso_sources(db, project_factory):
    """秘塔问答：真实响应把 citations 放在 choices[0].message，仍要归一成可审计引用。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "fast",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "广州基地有 AIGC 课程。",
                            "citations": [
                                {
                                    "title": "广州 AI 实训基地课程",
                                    "link": "https://gz-base.example/courses",
                                    "summary": "课程覆盖 AIGC 工具与项目实训。",
                                    "date": "2026年11月20日",
                                }
                            ],
                        }
                    }
                ],
            },
        )

    with _mock_client(handler) as client:
        adapter = OpenAICompatibleAdapter(
            db,
            base_url="https://metaso.cn/api/v1",
            model="fast",
            api_key="mk-example",
            client=client,
            web_search_mode="metaso",
        )
        payload = adapter.collect(task)

    assert seen["url"] == "https://metaso.cn/api/v1/chat/completions"
    assert seen["body"]["model"] == "fast"
    assert payload.text == "广州基地有 AIGC 课程。"
    assert [citation.url for citation in payload.citations] == [
        "https://gz-base.example/courses"
    ]
    assert payload.citations[0].site_name is None
    assert payload.citations[0].snippet == "课程覆盖 AIGC 工具与项目实训。"
    assert payload.citations[0].published_at is not None
    assert payload.answer_kind == AnswerKind.ANSWER


def test_build_entry_adapter_selects_metaso_search(db, project_factory, monkeypatch):
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = "https://metaso.cn/api/v1"
    entry.model_name = "fast"
    entry.credential_ref = "METASO_API_KEY"
    entry.supports_search = True
    monkeypatch.setenv("METASO_API_KEY", "mk-example")
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.web_search_mode == "metaso"


def test_build_entry_adapter_selects_kimi_web_search(db, project_factory, monkeypatch):
    """入口 supports_search=true 时，Kimi 必须切到 Responses 联网适配器。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = "https://api.moonshot.cn/v1"
    entry.model_name = "kimi-k3"
    entry.credential_ref = "MOONSHOT_API_KEY"
    entry.supports_search = True
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-example")
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, KimiWebSearchAdapter)
    assert adapter.endpoint == "https://api.moonshot.cn/v1/responses"


def test_build_entry_adapter_selects_qwen_web_search(db, project_factory, monkeypatch):
    """千问 supports_search=true 时必须切到 Responses web_search 适配器。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    entry.model_name = "qwen3.8-max"
    entry.credential_ref = "DASHSCOPE_API_KEY"
    entry.supports_search = True
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-example")
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, QwenWebSearchAdapter)
    assert adapter.endpoint == "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"


def test_build_entry_adapter_keeps_qwen_chat_when_search_disabled(db, project_factory):
    """不支持联网的千问入口仍走普通 Chat，不误切 Responses。"""
    task = _make_task(db, project_factory(f"local-{uuid.uuid4().hex[:6]}"))
    entry = db.get(AiEngineEntry, task.engine_entry_id)
    entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
    entry.entry_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    entry.model_name = "qwen3.8-max"
    entry.credential_ref = None
    entry.supports_search = False
    db.flush()

    adapter = build_entry_adapter(db, entry)

    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.web_search_mode is None


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
