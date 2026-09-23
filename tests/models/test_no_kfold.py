"""Random k-fold strings must not appear in the models package."""

from __future__ import annotations

from pathlib import Path

FORBIDDEN = ("KFold", "train_test_split", "Stratified")


def test_models_package_has_no_kfold_or_train_test_split() -> None:
    root = Path("models")
    hits: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for token in FORBIDDEN:
            if token in text:
                hits.append(f"{path}: {token}")
    assert hits == []
