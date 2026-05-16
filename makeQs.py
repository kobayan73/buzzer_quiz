#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convert a quiz spreadsheet exported from Numbers / Google Sheets into questions.json.

Recommended workflow:
1. Open beginer_demo.numbers in Numbers.
2. File > Export To > CSV...
3. Save it as beginer_demo.csv in this same folder.
4. Run:
   python3 makeQs.py beginer_demo.csv questions.json

The script also accepts TSV files.

Expected columns, using either snake_case or camelCase:
- question_id / id
- question_text / questionText / text
- answer_display / answerDisplay / answer
- answer_normalized / answerNormalized  optional
- answer_chars / answerChars            optional

Output format:
[
  {
    "id": "geo_000001_beg_com",
    "text": "...",
    "displayAnswer": "Japan",
    "normalizedAnswer": "japan",
    "answerChars": ["j", "a", "p", "a", "n"]
  }
]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_INPUT = "beginer_demo.csv"
DEFAULT_OUTPUT = "questions.json"


def normalize_key(key: str) -> str:
    """Normalize column names so question_text, questionText, and Question Text match."""
    return re.sub(r"[^a-z0-9]", "", key.strip().lower())


def pick(row: Dict[str, str], *names: str) -> str:
    """Pick the first non-empty value from a row using flexible column names."""
    normalized_row = {normalize_key(k): v for k, v in row.items()}
    for name in names:
        value = normalized_row.get(normalize_key(name), "")
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def normalize_answer(value: str) -> str:
    """
    Convert display answers into the in-game normalized answer.

    Examples:
    - "World War 2" -> "worldwar2"
    - "World War II" -> "worldwar2"
    - "Mona Lisa" -> "monalisa"
    """
    text = str(value).strip().lower()
    text = re.sub(r"\bii\b", "2", text)
    text = text.replace("ⅱ", "2")
    text = text.replace("Ⅱ", "2")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def parse_answer_chars(value: str, normalized_answer: str) -> List[str]:
    """
    Parse answer chars from the spreadsheet.

    Accepts:
    - JSON array: ["j","a","p","a","n"]
    - comma separated: j,a,p,a,n
    - plain string: japan
    If blank, it uses normalized_answer.
    """
    value = str(value or "").strip()
    if not value:
        return list(normalized_answer)

    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(x).strip().lower() for x in parsed if str(x).strip() != ""]
    except json.JSONDecodeError:
        pass

    if "," in value:
        return [part.strip().lower() for part in value.split(",") if part.strip()]

    compact = normalize_answer(value)
    return list(compact)


def detect_delimiter(path: Path) -> str:
    """Detect CSV or TSV delimiter from a small sample."""
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:4096]
    if "\t" in sample:
        return "\t"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";"])
        return dialect.delimiter
    except csv.Error:
        return ","


def read_rows(input_path: Path) -> List[Dict[str, str]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if input_path.suffix.lower() == ".numbers":
        raise ValueError(
            "Python cannot reliably read .numbers files directly. "
            "Open the file in Numbers and export it as CSV first: "
            "File > Export To > CSV..."
        )

    delimiter = detect_delimiter(input_path)
    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("No header row found. The first row must contain column names.")
        return list(reader)


def convert_row(row: Dict[str, str], index: int) -> Optional[Dict[str, Any]]:
    question_id = pick(row, "id", "question_id", "questionId") or f"q_{index + 1:06d}"
    question_text = pick(row, "text", "question_text", "questionText")
    display_answer = pick(row, "displayAnswer", "answer_display", "answerDisplay", "answer")

    if not question_text or not display_answer:
        return None

    normalized_answer = pick(row, "normalizedAnswer", "answer_normalized", "answerNormalized")
    if not normalized_answer:
        normalized_answer = normalize_answer(display_answer)
    else:
        normalized_answer = normalize_answer(normalized_answer)

    raw_answer_chars = pick(row, "answerChars", "answer_chars", "answerchars")
    answer_chars = parse_answer_chars(raw_answer_chars, normalized_answer)

    return {
        "id": question_id,
        "text": question_text,
        "displayAnswer": display_answer,
        "normalizedAnswer": normalized_answer,
        "answerChars": answer_chars,
    }


def convert_file(input_path: Path, output_path: Path) -> List[Dict[str, Any]]:
    rows = read_rows(input_path)
    questions: List[Dict[str, Any]] = []
    skipped = 0

    for i, row in enumerate(rows):
        question = convert_row(row, i)
        if question is None:
            skipped += 1
            continue
        questions.append(question)

    if not questions:
        raise ValueError("No valid questions were found. Check column names and data.")

    output_path.write_text(
        json.dumps(questions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 72)
    print("Conversion complete")
    print("=" * 72)
    print(f"Input   : {input_path}")
    print(f"Output  : {output_path}")
    print(f"Questions written : {len(questions)}")
    print(f"Rows skipped      : {skipped}")
    print("\nPreview:")
    for q in questions[:3]:
        print(f"- {q['id']} | {q['displayAnswer']} | {q['text'][:70]}...")

    return questions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert quiz CSV/TSV exported from Numbers into questions.json."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Input CSV/TSV file. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=DEFAULT_OUTPUT,
        help=f"Output JSON file. Default: {DEFAULT_OUTPUT}",
    )
    args = parser.parse_args()

    try:
        convert_file(Path(args.input), Path(args.output))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
