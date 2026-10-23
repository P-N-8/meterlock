from dataclasses import dataclass

NANODOLLARS_PER_DOLLAR = 1_000_000_000


@dataclass(frozen=True)
class AlphaConfig:
    supported_models: tuple[str, ...] = ("gpt-5.6-luna", "gpt-6-luna", "gpt-6-sol")
    min_output_tokens: int = 16
    max_output_tokens_cap: int = 500
    minimum_budget_nd: int = 1_000  # $0.000001


CONFIG = AlphaConfig()
