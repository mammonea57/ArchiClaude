from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class FeatureFlag:
    key: str
    enabled_globally: bool
    enabled_for_user_ids: list[UUID] = field(default_factory=list)
    description: str | None = None


def is_enabled(flag: FeatureFlag, user_id: UUID | None) -> bool:
    if flag.enabled_globally:
        return True
    if user_id is None:
        return False
    return user_id in flag.enabled_for_user_ids
