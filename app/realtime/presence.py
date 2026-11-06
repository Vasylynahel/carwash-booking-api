"""Хто зараз онлайн. Стан у пам'яті процесу: одна людина може мати кілька з'єднань (вкладок)."""

_online: dict[int, dict] = {}


def add(user_id: int, role: str, name: str, sid: str) -> bool:
    """Повертає True, якщо це перше з'єднання користувача (він щойно став онлайн)."""
    entry = _online.setdefault(user_id, {"role": role, "name": name, "sids": set()})
    first = not entry["sids"]
    entry["sids"].add(sid)
    return first


def remove(user_id: int, sid: str) -> bool:
    """Повертає True, якщо закрито останнє з'єднання користувача (він став офлайн)."""
    entry = _online.get(user_id)
    if not entry:
        return False
    entry["sids"].discard(sid)
    if not entry["sids"]:
        del _online[user_id]
        return True
    return False


def snapshot() -> list[dict]:
    return [
        {"user_id": uid, "role": e["role"], "name": e["name"], "connections": len(e["sids"])}
        for uid, e in sorted(_online.items())
    ]


def clear() -> None:
    _online.clear()
