from __future__ import annotations

from .storage import Store


def report(store: Store, account: str = "default") -> str:
    counts = store.count(account)
    recorded = sum(counts.values())
    confirmed_republications = store.confirmed_republication_ids(account)
    unique_after_audit = max(0, recorded - len(confirmed_republications))
    confirmed = counts.get("success", 0) + counts.get("already_applied", 0)
    unique_confirmed = max(0, confirmed - len(confirmed_republications))
    lines = [f"Recorded application vacancy IDs: {recorded}",
             f"Confirmed republished duplicates: {len(confirmed_republications)}",
             f"Unique application vacancies after republication audit: {unique_after_audit}",
             f"Confirmed application vacancy IDs: {confirmed}",
             f"Unique confirmed applications after republication audit: {unique_confirmed}",
             f"Application attempts/events: {store.event_count(account)}"]
    lines.extend(f"{status}: {counts[status]}" for status in sorted(counts))
    latest = store.latest_sync(account)
    if latest:
        lines.append(f"Last status sync: {latest['created_at']} ({latest['status']}, items={latest['item_count']})")
    else:
        lines.append("Last status sync: never")
    return "\n".join(lines)
