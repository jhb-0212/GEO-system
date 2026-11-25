"""知识库：DOCX 解析、切块、检索、候选事实采纳/驳回与扫描件拒绝。"""

from __future__ import annotations

import io
import uuid

from docx import Document
from pptx import Presentation
from pypdf import PdfWriter

from app.core.security import create_access_token
from app.models import Fact, FactVersion, KnowledgeCandidateFact, KnowledgeChunk, KnowledgeDocument
from app.models.enums import FactStatus, KnowledgeParseStatus, RoleCode
from sqlalchemy import func, select


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _docx_bytes() -> bytes:
    document = Document()
    document.add_heading("广州成才人工智能培训有限公司知识手册", level=1)
    paragraphs = [
        "广州成才人工智能培训有限公司成立于2018年，总部位于广州市天河区珠江新城华夏路10号。",
        "公司主营AIGC漫剧实训、GEO搜索优化课程与AI内容制作培训，课程周期为12周。",
        "机构拥有全职讲师18人，其中主讲讲师均具备五年以上内容制作与项目管理经验。",
        "公司获得广东省人工智能产业协会颁发的培训服务能力认证，证书编号为GD-AI-2024-018。",
        "报名咨询电话为020-88886666，官方邮箱为hello@chengcai.ai，官网地址为https://chengcai.ai。",
    ]
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    for index in range(1, 16):
        document.add_paragraph(
            f"第{index}节：我们为学员提供从选题、脚本、分镜到成片交付的完整实训流程，"
            "每个阶段都有讲师逐镜头批改，并在结课后提供作品集辅导与就业推荐服务。"
        )
    document.add_paragraph(
        "就业服务包括简历诊断、作品集包装、模拟面试与岗位内推，2025年学员就业率为86%。"
    )
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pptx_bytes() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "品牌介绍"
    slide.placeholders[1].text = "广州成才人工智能培训有限公司位于广州市天河区珠江新城，报名电话020-88886666。"
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _upload(client, project, user, *, title: str, filename: str, content: bytes, content_type: str) -> str:
    response = client.post(
        f"/api/v1/projects/{project.id}/materials",
        data={"title": title, "category": "document"},
        files={"file": (filename, content, content_type)},
        headers=_auth(user),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def test_docx_parse_chunks_search_and_candidate_review(
    client, db, project_factory, user_factory, member_factory, monkeypatch, tmp_path
):
    monkeypatch.setattr("app.core.config.settings.evidence_local_root", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.knowledge_embedding_base_url", "")
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"kb-{suffix}")
    editor = user_factory(f"kb-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    material_id = _upload(
        client,
        project,
        editor,
        title="品牌知识手册",
        filename="handbook.docx",
        content=_docx_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    parsed = client.post(
        f"/api/v1/projects/{project.id}/knowledge/documents/{material_id}/parse",
        headers=_auth(editor),
    )
    assert parsed.status_code == 200, parsed.text
    data = parsed.json()["data"]
    assert data["parse_status"] == "ready"
    assert data["page_count"] == 1
    assert data["chunk_count"] >= 2
    assert data["candidate_count"] >= 3

    doc_id = data["id"]
    chunks = client.get(
        f"/api/v1/projects/{project.id}/knowledge/documents/{doc_id}/chunks",
        headers=_auth(editor),
    )
    assert chunks.status_code == 200, chunks.text
    items = chunks.json()["data"]
    assert items and all(item["text"] for item in items)
    assert all(150 <= item["token_count"] <= 900 for item in items)

    found = client.get(
        f"/api/v1/projects/{project.id}/knowledge/search",
        params={"q": "珠江新城 地址", "top_k": 5},
        headers=_auth(editor),
    )
    assert found.status_code == 200, found.text
    result = found.json()["data"]
    assert result["search_mode"] == "lexical_trigram"
    assert result["items"]
    assert result["items"][0]["document_id"] == doc_id

    candidates = client.get(
        f"/api/v1/projects/{project.id}/knowledge/candidate-facts",
        params={"status": "suggested", "document_id": doc_id},
        headers=_auth(editor),
    )
    assert candidates.status_code == 200, candidates.text
    rows = candidates.json()["data"]
    assert rows
    target = next(row for row in rows if "电话" in row["claim_text"] or "地址" in row["claim_text"])

    accepted = client.post(
        f"/api/v1/projects/{project.id}/knowledge/candidate-facts/{target['id']}/accept",
        json={"fact_key": f"公司联系方式-{suffix}", "change_note": "人工核对官网"},
        headers=_auth(editor),
    )
    assert accepted.status_code == 200, accepted.text
    accepted_data = accepted.json()["data"]
    assert accepted_data["candidate"]["status"] == "accepted"

    fact = db.scalar(select(Fact).where(Fact.project_id == project.id, Fact.fact_key == f"公司联系方式-{suffix}"))
    assert fact is not None
    assert fact.approval_status == FactStatus.DRAFT
    version = db.scalar(select(FactVersion).where(FactVersion.fact_id == fact.id))
    assert version is not None
    assert version.version_no == 1

    second = next(row for row in rows if row["id"] != target["id"])
    rejected = client.post(
        f"/api/v1/projects/{project.id}/knowledge/candidate-facts/{second['id']}/reject",
        json={"note": "口径不够具体"},
        headers=_auth(editor),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "rejected"


def test_pdf_without_text_is_unsupported_scan(
    client, db, project_factory, user_factory, member_factory, monkeypatch, tmp_path
):
    monkeypatch.setattr("app.core.config.settings.evidence_local_root", str(tmp_path))
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"kb-scan-{suffix}")
    editor = user_factory(f"kb-scan-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)

    material_id = _upload(
        client, project, editor, title="扫描件", filename="scan.pdf", content=buffer.getvalue(), content_type="application/pdf"
    )
    parsed = client.post(
        f"/api/v1/projects/{project.id}/knowledge/documents/{material_id}/parse",
        headers=_auth(editor),
    )
    assert parsed.status_code == 200, parsed.text
    data = parsed.json()["data"]
    assert data["parse_status"] == "unsupported"
    assert "unsupported_scan" not in (data["error"] or "")  # 对外只给中文原因，不暴露内部 code
    assert "OCR" in (data["error"] or "")

    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == uuid.UUID(data["id"])))
    assert document is not None
    assert document.parse_status == KnowledgeParseStatus.UNSUPPORTED
    assert db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)) == 0
    assert db.scalar(select(func.count()).select_from(KnowledgeCandidateFact).where(KnowledgeCandidateFact.document_id == document.id)) == 0


def test_pptx_is_parseable_and_keeps_slide_page(
    client, db, project_factory, user_factory, member_factory, monkeypatch, tmp_path
):
    monkeypatch.setattr("app.core.config.settings.evidence_local_root", str(tmp_path))
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"kb-ppt-{suffix}")
    editor = user_factory(f"kb-ppt-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    material_id = _upload(
        client,
        project,
        editor,
        title="品牌介绍 PPT",
        filename="intro.pptx",
        content=_pptx_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    parsed = client.post(
        f"/api/v1/projects/{project.id}/knowledge/documents/{material_id}/parse",
        headers=_auth(editor),
    )
    assert parsed.status_code == 200, parsed.text
    data = parsed.json()["data"]
    assert data["parse_status"] == "ready"
    assert data["page_count"] == 1
    assert data["chunk_count"] == 1
    assert data["candidate_count"] >= 1

    chunks = client.get(
        f"/api/v1/projects/{project.id}/knowledge/documents/{data['id']}/chunks",
        headers=_auth(editor),
    )
    assert chunks.status_code == 200, chunks.text
    assert chunks.json()["data"][0]["page_from"] == 1
    assert "珠江新城" in chunks.json()["data"][0]["text"]


def test_hybrid_vector_search_recalls_synonym_without_lexical_match(
    client, db, project_factory, user_factory, member_factory, monkeypatch, tmp_path
):
    monkeypatch.setattr("app.core.config.settings.evidence_local_root", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.knowledge_embedding_base_url", "http://embedding.test")
    monkeypatch.setattr("app.core.config.settings.knowledge_embedding_model", "test-embed")
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"kb-vector-{suffix}")
    editor = user_factory(f"kb-vector-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    def fake_embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for value in texts:
            target = any(term in value for term in ("珠江新城", "办公地点", "公司地址"))
            vectors.append([1.0 if target else 0.0, 0.0 if target else 1.0] + [0.0] * 1022)
        return vectors

    monkeypatch.setattr("app.services.knowledge_embedding.embed_texts", fake_embed)

    material_id = _upload(
        client,
        project,
        editor,
        title="地址手册",
        filename="address.docx",
        content=_docx_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    parsed = client.post(
        f"/api/v1/projects/{project.id}/knowledge/documents/{material_id}/parse",
        headers=_auth(editor),
    )
    assert parsed.status_code == 200, parsed.text
    data = parsed.json()["data"]
    assert data["embedding_status"] == "ready"
    assert data["search_mode"] == "hybrid_vector"

    # “办公地点”在原文中没有词法命中，只能靠向量把“珠江新城地址”召回。
    found = client.get(
        f"/api/v1/projects/{project.id}/knowledge/search",
        params={"q": "办公地点", "top_k": 5},
        headers=_auth(editor),
    )
    assert found.status_code == 200, found.text
    result = found.json()["data"]
    assert result["search_mode"] == "hybrid_vector"
    assert result["embedding_status"] == "ready"
    assert result["items"]
    assert result["items"][0]["vector_similarity"] >= 0.9
    assert "珠江新城" in result["items"][0]["text"]
