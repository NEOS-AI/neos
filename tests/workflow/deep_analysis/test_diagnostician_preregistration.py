from pathlib import Path

import yaml

PREREG = Path("scripts/diagnostician_backtest")


def _load(name: str) -> dict:
    return yaml.safe_load((PREREG / name).read_text(encoding="utf-8"))


def test_label_set_is_closed_and_sized():
    labels = _load("labels.yaml")["labels"]
    assert len(labels) == len(set(labels)), "라벨이 중복된다"
    assert len(labels) == 17


def test_every_key_label_is_in_the_closed_set():
    labels = set(_load("labels.yaml")["labels"])
    samples = _load("answer_key.yaml")["samples"]
    for sample_id, entry in samples.items():
        for field in ("truth", "contemporaneous"):
            unknown = set(entry[field]) - labels
            assert not unknown, f"#{sample_id} {field}에 집합 밖 라벨: {unknown}"


def test_answer_key_covers_samples_11_through_16():
    samples = _load("answer_key.yaml")["samples"]
    assert set(samples) == {"11", "12", "13", "14", "15", "16"}
    for entry in samples.values():
        assert entry["quote"], "인용 없는 정답은 근거 없는 정답이다"
        assert entry["decision"].startswith("D")


def test_signal_map_covers_every_label():
    labels = set(_load("labels.yaml")["labels"])
    signals = _load("signal_map.yaml")["signals"]
    assert set(signals) == labels, "라벨과 신호 지도가 어긋난다"
