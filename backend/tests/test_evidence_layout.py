"""证据包原始文件：样本 id 唯一落盘，同题多样本不覆盖。"""

import hashlib

from app.services.evidence_layout import sample_artifact_paths, write_sample_artifacts


def test_two_samples_same_engine_question_do_not_overwrite(tmp_path):
    first_answer, first_response = sample_artifact_paths("doubao", "Q01", "sample-1")
    second_answer, second_response = sample_artifact_paths("doubao", "Q01", "sample-2")
    assert first_answer != second_answer
    assert first_response != second_response
    assert first_answer.parent == second_answer.parent  # engine/question 目录层级保留

    write_sample_artifacts(
        tmp_path, engine="doubao", question="Q01", sample_id="sample-1",
        raw_answer="第一个样本", raw_response={"sample": 1},
    )
    write_sample_artifacts(
        tmp_path, engine="doubao", question="Q01", sample_id="sample-2",
        raw_answer="第二个样本", raw_response={"sample": 2},
    )

    assert (tmp_path / first_answer).read_text(encoding="utf-8") == "第一个样本"
    assert (tmp_path / second_answer).read_text(encoding="utf-8") == "第二个样本"
    assert '"sample": 1' in (tmp_path / first_response).read_text(encoding="utf-8")
    assert '"sample": 2' in (tmp_path / second_response).read_text(encoding="utf-8")

    manifest = {
        rel.as_posix(): hashlib.sha256((tmp_path / rel).read_bytes()).hexdigest()
        for rel in (first_answer, second_answer, first_response, second_response)
    }
    assert len(set(manifest.values())) == 4
