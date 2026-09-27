"""Approved GEPA overlay text for a coding turn. No database on the default path."""

from __future__ import annotations


async def load_approved_components(owner_id: str) -> dict[str, str] | None:
    """Approved coding overlay for owner:{id}. Tests replace this function."""
    from neos.gepa_opt.store import GepaOptStore
    from neos.learn.lessons import resolve_lesson_session_factory
    from neos.learn.policy import namespace

    store = GepaOptStore(resolve_lesson_session_factory())
    return await store.approved_components(namespace(owner_id), "coding_overlay")


async def coding_turn_overlay(static_system: str, owner_id: str | None) -> str:
    from neos.config.settings import settings

    if not settings.config.learn.gepa_overlay:
        return static_system
    if not owner_id:
        return static_system
    components = await load_approved_components(owner_id)
    if not components:
        return static_system
    blocks = [f"### {name}\n{components[name]}" for name in sorted(components)]
    return static_system + "\n\n## Optimized overlay\n" + "\n".join(blocks)
