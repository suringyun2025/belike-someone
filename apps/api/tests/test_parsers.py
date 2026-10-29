from __future__ import annotations

from pathlib import Path

import pytest

from app.parsers import chunk_text, parse_file
from app.security import contains_secret, redact_text


def test_redaction_patterns():
    text = "联系 test@example.com 或 13800138000，密钥 sk-abcdefghijklmnop1234"
    redacted, count = redact_text(text)
    assert count >= 3
    assert "test@example.com" not in redacted
    assert "13800138000" not in redacted
    assert "sk-abcdefghijklmnop1234" not in redacted
    assert contains_secret(text)


def test_markdown_parsing_and_offsets(tmp_path: Path):
    path = tmp_path / "note.md"
    path.write_text(
        "# 决策\n\n我通常先确认约束，再比较成本。\n\n## 风格\n\n我表达时先给结论。\n",
        encoding="utf-8",
    )
    parsed = parse_file(path, "note.md")
    assert parsed.parser == "markdown"
    assert len(parsed.blocks) >= 4
    assert parsed.blocks[1].heading == "决策"
    assert parsed.blocks[1].start_char >= 0
    assert parsed.blocks[-1].end_char > parsed.blocks[0].start_char
    chunks = chunk_text(parsed.blocks, chunk_chars=60, overlap=10)
    assert chunks
    assert chunks[0]["start_char"] <= chunks[0]["end_char"]


def test_jsonl_chat_parsing(tmp_path: Path):
    path = tmp_path / "chat.jsonl"
    path.write_text(
        '{"sender":"架构师","timestamp":"2026-01-01","content":"我通常先复现问题。"}\n'
        '{"sender":"同事","timestamp":"2026-01-01","content":"好的。"}\n',
        encoding="utf-8",
    )
    parsed = parse_file(path, "chat.jsonl", source_type="chat")
    assert parsed.parser == "jsonl-chat"
    assert any(block.kind == "chat" for block in parsed.blocks)
    assert "复现问题" in parsed.text


def test_scanned_image_ocr(tmp_path: Path):
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path / "image.png"
    image = Image.new("RGB", (720, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 80), "HELLO OCR TEST", fill="black", font=ImageFont.load_default(size=56))
    image.save(path)
    parsed = parse_file(path, "image.png", source_type="image")
    assert parsed.parser == "rapidocr"
    assert parsed.blocks
    assert "HELLO" in parsed.text.upper()
