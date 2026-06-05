from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    script_location: Path
    version_strategy: str = field(default="node")
