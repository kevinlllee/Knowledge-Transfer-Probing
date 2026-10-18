#!/usr/bin/env python3
"""Score text QA responses from different models using normalized exact match."""

# Scoring flow:
# 1. Read raw_output and the reference answer (meta.answer or a flat answer field).
#    Reject missing responses, invalid references and duplicate entity records.
# 2. Remove complete <think>...</think> blocks from the response. Discard any
#    remaining <think> and everything after it, then remove control tokens.
# 3. Normalize both the cleaned response and the reference: lowercase, trim
#    surrounding whitespace and trailing periods (. or 。), and collapse internal
#    whitespace to single spaces. Preserve other punctuation and wording.
# 4. Mark the response correct only if the entire normalized strings match.
#    Empty responses are incorrect; no keyword extraction or semantic matching.
# 5. Compute correct / total overall and per task. An empty dataset has null
#    accuracy. Optionally write individual results and the summary to files.

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re


THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
CONTROL_TOKEN_RE = re.compile(r"<\|[a-zA-Z_]+\|>")


def strip_think(text: str) -> tuple[str, bool, bool]:
    """Remove thinking blocks and control tokens from a model response."""
    has_think = "<think>" in text
    closed = has_think and "</think>" in text
    text = THINK_BLOCK_RE.sub("", text)
    if "<think>" in text:
        text = text[:text.index("<think>")]
    text = CONTROL_TOKEN_RE.sub("", text)
    return text.strip(), has_think, closed


def normalize(text: str) -> str:
    """Normalize case, whitespace and trailing periods, preserving other punctuation."""
    text = text.strip().lower().rstrip(".。 ").strip()
    return re.sub(r"\s+", " ", text)


def judge(raw_output: str, answer: str) -> dict:
    """Return a strict match against one reference answer, with cleaning diagnostics."""
    prediction, has_think, closed = strip_think(raw_output)
    return {
        "prediction": prediction,
        "correct": normalize(prediction) == normalize(answer),
        "has_think": has_think,
        "think_closed": closed,
    }


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def score_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """Score QA rows with raw_output, or flat model response records.

    Missing responses are invalid input. An empty response is a scored error.
    Every record is counted once; duplicate (task, instance_id) keys are rejected.
    """
    results = []
    seen = set()
    per_task = defaultdict(list)
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Record {index}: expected a JSON object")
        meta = row.get("meta", row)
        if not isinstance(meta, dict):
            raise ValueError(f"Record {index}: meta must be a JSON object")
        for field in ("task", "instance_id", "answer"):
            value = meta.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Record {index}: {field} must be a nonempty string")
        if not normalize(meta["answer"]):
            raise ValueError(f"Record {index}: answer must not normalize to an empty string")
        raw_output = row.get("raw_output")
        if not isinstance(raw_output, str):
            raise ValueError(f"Record {index}: raw_output must be a string (empty is allowed)")
        key = (meta["task"], meta["instance_id"])
        if key in seen:
            raise ValueError(f"Record {index}: duplicate task/instance_id: {key}")
        seen.add(key)
        result = {
            "task": meta["task"],
            "instance_id": meta["instance_id"],
            "answer": meta["answer"],
            "raw_output": raw_output,
            **judge(raw_output, meta["answer"]),
        }
        results.append(result)
        per_task[meta["task"]].append(result)

    def stats(records: list[dict]) -> dict:
        total = len(records)
        correct = sum(record["correct"] for record in records)
        return {"total": total, "correct": correct,
                "accuracy": correct / total if total else None}

    summary = {
        "metric": "normalized_exact_match",
        "overall": stats(results),
        "per_task": {task: stats(per_task[task]) for task in sorted(per_task)},
    }
    return results, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="QA JSONL with raw_output added, or flat model response JSONL")
    parser.add_argument("--output-dir", type=Path,
                        help="Optionally write results.jsonl and summary.json here")
    args = parser.parse_args()
    try:
        results, summary = score_rows(read_jsonl(args.input))
        summary_text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "results.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results),
                encoding="utf-8",
            )
            (args.output_dir / "summary.json").write_text(summary_text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(summary_text, end="")


if __name__ == "__main__":
    main()
