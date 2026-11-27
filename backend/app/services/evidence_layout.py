"""证据包原始文件布局：一个样本一份文件，不允许同题多份样本互相覆盖。

目录仍保留 `engine/question` 便于人工浏览，文件名使用 `sample_id` 作为唯一标识；
同一引擎同一题的两个样本、多个 attempt 都会落成不同文件。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sample_artifact_paths(engine: str, question: str, sample_id: str) -> tuple[Path, Path]:
    stem = f"{sample_id}.md"
    answer_path = Path("raw_answers") / (engine or "unknown") / (question or "Q??") / stem
    response_path = Path("raw_responses") / (engine or "unknown") / (question or "Q??") / f"{sample_id}.json"
    return answer_path, response_path


def write_sample_artifacts(
    out_dir: Path,
    *,
    engine: str,
    question: str,
    sample_id: str,
    raw_answer: str,
    raw_response: Any,
) -> tuple[Path, Path]:
    """落盘一个样本的原始回答与原始响应；返回相对 out_dir 的路径。"""
    answer_path, response_path = sample_artifact_paths(engine, question, sample_id)
    (out_dir / answer_path).parent.mkdir(parents=True, exist_ok=True)
    (out_dir / answer_path).write_text(raw_answer, encoding="utf-8")
    (out_dir / response_path).parent.mkdir(parents=True, exist_ok=True)
    (out_dir / response_path).write_text(
        json.dumps(raw_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return answer_path, response_path
