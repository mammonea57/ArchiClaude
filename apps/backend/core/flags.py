from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class FeatureFlag:
    key: str
    enabled_globally: bool
    enabled_for_user_ids: list[UUID] = field(default_factory=list)
    description: str | None = None


async def is_enabled(flag: FeatureFlag, user_id: UUID | None) -> bool:
    """Retourne True si le flag est actif pour cet utilisateur.

    Règles :
    - `enabled_globally=True` écrase tout (actif pour tout le monde, y compris anonymes)
    - sinon, actif uniquement si `user_id` est dans `enabled_for_user_ids`
    - anonyme (user_id=None) n'est jamais actif sauf si global
    """
    if flag.enabled_globally:
        return True
    if user_id is None:
        return False
    return user_id in flag.enabled_for_user_ids
