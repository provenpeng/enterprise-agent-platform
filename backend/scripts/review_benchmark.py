"""Prepare answer review sheets and score two independent reviews."""

import argparse
import json
from pathlib import Path

from app.evaluation.human_review import review_template, score_reviews


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--report", type=Path, required=True)
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    score = commands.add_parser("score")
    score.add_argument("--report", type=Path, required=True)
    score.add_argument("--dataset", type=Path, required=True)
    score.add_argument("--reviews", type=Path, nargs=2, required=True)
    score.add_argument("--min-support", type=float, default=0.9)
    score.add_argument("--min-agreement", type=float, default=0.9)
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        result = review_template(arguments.report, arguments.dataset)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Review sheet: {arguments.output}")
        return
    if not 0 <= arguments.min_support <= 1 or not 0 <= arguments.min_agreement <= 1:
        parser.error("Review thresholds must be between 0 and 1")
    result = score_reviews(arguments.report, arguments.dataset, arguments.reviews)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        result["fact_support_rate"] < arguments.min_support
        or result["agreement_rate"] < arguments.min_agreement
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
