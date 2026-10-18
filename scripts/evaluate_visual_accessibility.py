#!/usr/bin/env python3
"""Score visual accessibility from VLM responses."""

# Scoring flow:
# 1. Read each VLM response from raw_output and its reference attributes from
#    meta.key_info and meta.entities. Task and instance_id identify the sample.
# 2. Extract the response JSON, accepting JSON code fences and surrounding text.
# 3. Apply the task's rules:
#    color: use the VLM's pass judgment;
#    count: match the integer count and require all countability checks;
#    shape: exactly match the canonical shape label and require all badge checks;
#    spatial: exactly match the orientation and ordered color labels, plus all
#             flag checks. Labels are case-sensitive; no synonyms, translations,
#             extra wording, or whitespace normalization are accepted.
#    number: match the jersey number numerically, regardless of player name;
#    text: match the normalized book title within the edit-distance tolerance,
#          regardless of author name;
#    size: match both country names and the larger country, regardless of the
#          map title or the values of the map's visual-check flags.
# 4. For book titles and country names, allow at most 1, 2, or 3 character edits
#    for reference lengths <= 5, <= 10, or > 10 after normalization. A country
#    name must match a unique nearest candidate; both countries must be found.

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re


SHAPES = ("triangle", "square", "pentagon", "five-pointed star", "circle")
COLORS = ("black", "white", "red", "yellow", "blue", "green")
ORIENTATIONS = ("vertical", "horizontal")
FLAGS = {
    "count": ("easy_to_count", "all_fully_visible", "no_overlap",
              "target_is_main_subject", "reasonable_scene"),
    "shape": ("shape_easy_to_identify", "matches_expected_shape", "exactly_one_badge",
              "badge_fully_visible", "recognizable_as_badge"),
    "spatial": ("exactly_three_equal_stripes", "colors_easy_to_identify",
                "order_easy_to_identify", "flag_is_main_subject", "flag_fully_visible",
                "flag_is_landscape", "flag_not_rotated_or_flipped"),
    "size": ("exactly_two_countries", "map_fully_visible", "no_extra_map_content"),
}
REQUIRED_RESPONSE_FIELD = {
    "color": "pass", "count": "observed_count", "number": "observed_jersey_number",
    "shape": "observed_shape", "size": "observed_larger_country",
    "spatial": "observed_orientation", "text": "observed_book_title",
}


def extract_json(text: str) -> dict:
    """Read the VLM's JSON object, including fenced or prefixed responses."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        for opening, closing in (("{", "}"), ("[", "]")):
            start, end = text.find(opening), text.rfind(closing)
            if start != -1 and end > start:
                try:
                    data = json.loads(text[start:end + 1])
                    break
                except json.JSONDecodeError:
                    continue
        else:
            raise ValueError("Cannot parse JSON from the VLM response")
    if not isinstance(data, dict):
        raise ValueError("The VLM response must contain a JSON object")
    return data


def normalize_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 99 else None
    if isinstance(value, str) and re.fullmatch(r"\d{1,2}", value.strip()):
        return int(value.strip())
    return None


def normalize_name(value: object) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").casefold())


def normalize_title(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance with unit insertion, deletion and substitution costs."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def edit_tolerance(reference: str) -> int:
    return 1 if len(reference) <= 5 else 2 if len(reference) <= 10 else 3


def match_country(value: object, countries: list[str]) -> str | None:
    observed = normalize_name(value)
    if not observed:
        return None
    ranked = []
    for country in countries:
        reference = normalize_name(country)
        distance = edit_distance(observed, reference)
        if distance <= edit_tolerance(reference):
            ranked.append((distance, country))
    ranked.sort()
    if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
        return None
    return ranked[0][1]


def judge(task: str, raw_output: str, key_info: dict, entities: dict) -> dict:
    """Return the task judgment and observations; malformed responses raise ValueError."""
    data = extract_json(raw_output)
    required = REQUIRED_RESPONSE_FIELD[task]
    if required not in data:
        raise ValueError(f"Missing response field: {required}")
    flags = FLAGS.get(task, ())
    invalid = [field for field in flags if not isinstance(data.get(field), bool)]
    if invalid:
        raise ValueError(f"Missing or non-boolean response flags: {', '.join(invalid)}")
    checks = {}

    if task == "color":
        passed = bool(data["pass"])
    elif task == "count":
        observed = data["observed_count"]
        if isinstance(observed, bool) or (observed is not None and not isinstance(observed, int)):
            raise ValueError("observed_count must be an integer or null")
        passed = observed == key_info["count"] and all(data[field] for field in flags)
    elif task == "number":
        observed = normalize_number(data["observed_jersey_number"])
        passed = observed == key_info["number"]
        checks["normalized_observed_jersey_number"] = observed
    elif task == "shape":
        observed = data["observed_shape"]
        passed = observed == key_info["shape"] and all(data[field] for field in flags)
    elif task == "spatial":
        raw_colors = data.get("observed_color_order")
        if raw_colors is not None and not (isinstance(raw_colors, list) and len(raw_colors) == 3):
            raise ValueError("observed_color_order must be a three-item array or null")
        orientation = data["observed_orientation"]
        passed = (orientation == key_info["stripe_orientation"]
                  and raw_colors == key_info["stripe_colors"] and all(data[field] for field in flags))
    elif task == "text":
        observed = normalize_title(data["observed_book_title"])
        reference = normalize_title(key_info["title"])
        distance = edit_distance(observed, reference) if observed else None
        tolerance = edit_tolerance(reference)
        passed = distance is not None and distance <= tolerance
        checks.update(book_title_edit_distance=distance, book_title_edit_tolerance=tolerance)
    else:  # size
        names = data.get("observed_country_names")
        if names is not None and not (isinstance(names, list) and len(names) == 2):
            raise ValueError("observed_country_names must be a two-item array or null")
        countries = entities["countries"]
        matched = [match_country(name, countries) for name in (names or [])]
        names_match = sorted(filter(None, matched)) == sorted(countries)
        larger = match_country(data["observed_larger_country"], countries)
        larger_match = larger == key_info["larger_country"]
        passed = names_match and larger_match
        checks.update(fuzzy_observed_country_names=matched, fuzzy_country_names_match=names_match,
                      fuzzy_observed_larger_country=larger, fuzzy_larger_country_matches=larger_match)
    return {**data, **checks, "pass": bool(passed), "reason": str(data.get("reason", "")).strip()}


def validate_reference(task: str, key_info: dict, entities: dict) -> None:
    """Reject incomplete or invalid references before scoring responses."""
    if task not in REQUIRED_RESPONSE_FIELD:
        raise ValueError(f"Unsupported task: {task}")
    if not isinstance(key_info, dict) or not isinstance(entities, dict):
        raise ValueError("key_info and entities must be JSON objects")
    if task in ("count", "number"):
        value = key_info.get(task)
        if type(value) is not int or value < 0 or (task == "number" and value > 99):
            raise ValueError(f"Invalid reference {task}: {value!r}")
    elif task == "color" and key_info.get("color") not in COLORS:
        raise ValueError("Unknown reference color")
    elif task == "shape" and key_info.get("shape") not in SHAPES:
        raise ValueError("Unknown reference shape")
    elif task == "text":
        title = key_info.get("title")
        if not isinstance(title, str) or not normalize_title(title):
            raise ValueError("Reference title must be a nonempty string")
    elif task == "spatial":
        colors = key_info.get("stripe_colors")
        if (key_info.get("stripe_orientation") not in ORIENTATIONS
                or not isinstance(colors, list) or len(colors) != 3
                or any(not isinstance(color, str) or color not in COLORS for color in colors)):
            raise ValueError("Invalid reference stripe orientation or colors")
    elif task == "size":
        countries = entities.get("countries")
        if (not isinstance(countries, list) or len(countries) != 2
                or any(not isinstance(name, str) or not normalize_name(name) for name in countries)
                or len({normalize_name(name) for name in countries}) != 2
                or key_info.get("larger_country") not in countries):
            raise ValueError("Reference must identify two distinct countries and the larger one")


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
    results = []
    seen = set()
    per_task = defaultdict(list)
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Record {index}: expected a JSON object")
        meta = row.get("meta", row)
        if not isinstance(meta, dict):
            raise ValueError(f"Record {index}: meta must be a JSON object")
        for field in ("task", "instance_id"):
            if not isinstance(meta.get(field), str) or not meta[field].strip():
                raise ValueError(f"Record {index}: missing {field}")
        task, instance_id = meta["task"], meta["instance_id"]
        key_info, entities = meta.get("key_info"), meta.get("entities", {})
        validate_reference(task, key_info, entities)
        raw_output = row.get("raw_output")
        if not isinstance(raw_output, str):
            raise ValueError(f"Record {index}: raw_output must be a string")
        key = (task, instance_id)
        if key in seen:
            raise ValueError(f"Record {index}: duplicate task/instance_id: {key}")
        seen.add(key)
        result = {"task": task, "instance_id": instance_id, "expected_key_info": key_info,
                  "raw_output": raw_output, "pass": None, "verdict": None, "error": None}
        try:
            verdict = judge(task, raw_output, key_info, entities)
            result.update({"pass": verdict["pass"], "verdict": verdict})
        except ValueError as exc:
            result["error"] = str(exc)
        results.append(result)
        per_task[task].append(result)

    def stats(records: list[dict]) -> dict:
        consistent = sum(record["pass"] is True for record in records)
        inconsistent = sum(record["pass"] is False for record in records)
        errors = sum(record["error"] is not None for record in records)
        judged = consistent + inconsistent
        return {"total": len(records), "consistent": consistent, "inconsistent": inconsistent,
                "error": errors, "consistent_rate": round(consistent / judged, 4) if judged else None}

    return results, {"metric": "visual_accessibility", "overall": stats(results),
                     "per_task": {task: stats(per_task[task]) for task in sorted(per_task)}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="JSONL containing reference metadata and raw_output from a VLM")
    parser.add_argument("--output-dir", type=Path,
                        help="Optionally write results.jsonl and summary.json here")
    args = parser.parse_args()
    try:
        results, summary = score_rows(read_jsonl(args.input))
        summary_text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "results.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results), encoding="utf-8")
            (args.output_dir / "summary.json").write_text(summary_text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(summary_text, end="")


if __name__ == "__main__":
    main()
