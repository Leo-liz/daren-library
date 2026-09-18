"""Uncooperated-creator calculator contract; no scraping or guessed formula."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from rating import DEFAULT_CONFIG_PATH


PLACEHOLDER_MESSAGE = "接口已预留、计算逻辑待定"


@dataclass(frozen=True)
class CalculatorInput:
    """Future calculator inputs supplied manually from authorized sources."""

    sales_volume: int
    play_count: int
    assumed_slot_fee_vnd: int
    assumed_commission_rate: float

    def __post_init__(self) -> None:
        values = {
            "销量": self.sales_volume,
            "播放量": self.play_count,
            "假设坑位费": self.assumed_slot_fee_vnd,
        }
        for label, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label}必须是非负整数")
        rate = self.assumed_commission_rate
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 <= float(rate) <= 1:
            raise ValueError("假设佣金率必须是 0..1 之间的数字")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "CalculatorInput":
        try:
            return cls(
                sales_volume=int(values["sales_volume"]),
                play_count=int(values["play_count"]),
                assumed_slot_fee_vnd=int(values["assumed_slot_fee_vnd"]),
                assumed_commission_rate=float(values["assumed_commission_rate"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("计算器输入需包含销量、播放量、假设坑位费、假设佣金率") from exc


@dataclass(frozen=True)
class CalculatorResult:
    available: bool
    message: str
    inputs: dict[str, Any]
    formula: Any
    value: None = None


def calculate(
    inputs: CalculatorInput,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> CalculatorResult:
    """Return the deliberate placeholder until a reviewed formula is configured."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    formula = config.get("calculator_formula")
    if formula is not None:
        raise NotImplementedError("calculator_formula 已配置，但本期未实现公式执行器")
    return CalculatorResult(False, PLACEHOLDER_MESSAGE, asdict(inputs), formula)
