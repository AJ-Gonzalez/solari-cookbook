"""Load search criteria and board tokens from TOML config (stdlib tomllib)."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CRITERIA = Path("criteria.toml")
DEFAULT_BOARDS = Path("boards.toml")


@dataclass
class Criteria:
    title_include: list[str]
    title_exclude: list[str]
    comp_min_usd: int
    degree_penalty: float
    loc_accept: list[str]
    loc_reject: list[str]
    desc_exclude: list[str]
    bestshot_focus: list[str] = field(default_factory=list)
    bestshot_priority: list[str] = field(default_factory=list)
    bestshot_priority_boost: float = 2.0

    def title_matches(self, title: str) -> bool:
        t = title.lower()
        if any(x in t for x in self.title_exclude):
            return False
        return any(i in t for i in self.title_include)

    def text_allowed(self, text: str) -> bool:
        """False when a description/title hits an excluded token
        (e.g. public-sector clearance requirements)."""
        t = (text or "").lower()
        return not any(x in t for x in self.desc_exclude)


def load_criteria(path: Path = DEFAULT_CRITERIA) -> Criteria:
    d = tomllib.loads(Path(path).read_text())
    return Criteria(
        title_include=d["titles"]["include"],
        title_exclude=d["titles"]["exclude"],
        comp_min_usd=d["comp"]["min_usd"],
        degree_penalty=d["rank"]["degree_penalty"],
        loc_accept=d["location"]["accept"],
        loc_reject=d["location"]["reject"],
        desc_exclude=d["filters"]["exclude_description"],
        bestshot_focus=d.get("bestshot", {}).get("focus", []),
        bestshot_priority=d.get("bestshot", {}).get("priority", []),
        bestshot_priority_boost=d.get("bestshot", {}).get("priority_boost", 2.0),
    )


def load_boards(path: Path = DEFAULT_BOARDS) -> dict:
    return tomllib.loads(Path(path).read_text())
