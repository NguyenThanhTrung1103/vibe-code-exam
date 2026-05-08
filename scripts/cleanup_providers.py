"""List, rename, or merge providers (vendors).

Fix the data behind one-letter / placeholder / lower-case vendor cards on
the public site without touching exams or questions.

Usage:
    # 1. List all providers — see what's actually there.
    python -m scripts.cleanup_providers list

    # 2. Rename in-place (dry-run by default; pass --apply to commit).
    python -m scripts.cleanup_providers rename 7 --name "Palo Alto" --slug palo-alto
    python -m scripts.cleanup_providers rename 7 --name "Palo Alto" --slug palo-alto --apply

    # 3. Merge: re-point every Course on SRC to DST, then delete SRC.
    python -m scripts.cleanup_providers merge --src 7 --dst 3
    python -m scripts.cleanup_providers merge --src 7 --dst 3 --apply

Safety:
  * Default is dry-run — script prints exactly what it WILL change.
  * `--apply` is required to actually commit.
  * `rename` updates only `providers.name`/`providers.slug`/`description`;
    Courses, Exams, Questions are untouched (FK is provider_id, stable).
  * `merge` re-parents `courses.provider_id` to DST. Source provider must
    have no remaining children before the row is deleted (DB enforces FK
    RESTRICT, script enforces it explicitly so the message is friendly).
  * No row is ever silently deleted. Print ALL pending mutations first.

Requires the same `DATABASE_URL` env / `.env` the app uses.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings  # noqa: F401  — load .env via pydantic-settings
from app.db import SessionLocal
from app.models.catalog import Course, Provider
from app.utils.slug import is_valid_slug


def _list_providers(args: argparse.Namespace) -> int:
    with SessionLocal() as s:
        rows = list(s.scalars(select(Provider).order_by(Provider.id)))
        if not rows:
            print("(no providers)")
            return 0
        course_counts = dict(
            s.execute(
                select(Course.provider_id, _count(Course.id)).group_by(Course.provider_id)
            ).all()
        )
        print(f"{'ID':>4}  {'NAME':<32}  {'SLUG':<24}  COURSES")
        for p in rows:
            print(
                f"{p.id:>4}  {(p.name or '')[:32]:<32}  "
                f"{(p.slug or '')[:24]:<24}  {course_counts.get(p.id, 0)}"
            )
    return 0


def _rename(args: argparse.Namespace) -> int:
    with SessionLocal() as s:
        provider = s.get(Provider, args.id)
        if provider is None:
            print(f"ERROR: provider id={args.id} not found", file=sys.stderr)
            return 2

        new_name = args.name if args.name is not None else provider.name
        new_slug = args.slug if args.slug is not None else provider.slug
        new_description = (
            args.description if args.description is not None else provider.description
        )

        if not new_name or not new_name.strip():
            print("ERROR: name cannot be empty", file=sys.stderr)
            return 2
        if not is_valid_slug(new_slug):
            print(
                f"ERROR: slug {new_slug!r} is invalid (lower-case alnum + hyphen, max 64)",
                file=sys.stderr,
            )
            return 2

        print("Will update provider:")
        print(f"  id        : {provider.id}")
        print(f"  name      : {provider.name!r:>32} -> {new_name!r}")
        print(f"  slug      : {provider.slug!r:>32} -> {new_slug!r}")
        print(
            f"  description: {(provider.description or '')[:40]!r:>32} "
            f"-> {(new_description or '')[:40]!r}"
        )

        if not args.apply:
            print("\n(dry-run — pass --apply to commit)")
            return 0

        provider.name = new_name.strip()
        provider.slug = new_slug
        provider.description = new_description
        try:
            s.commit()
        except IntegrityError as exc:
            s.rollback()
            print(f"ERROR: commit failed (likely slug collision): {exc.orig}", file=sys.stderr)
            return 3
        print("OK — provider updated.")
    return 0


def _merge(args: argparse.Namespace) -> int:
    if args.src == args.dst:
        print("ERROR: --src and --dst must differ", file=sys.stderr)
        return 2

    with SessionLocal() as s:
        src = s.get(Provider, args.src)
        dst = s.get(Provider, args.dst)
        if src is None:
            print(f"ERROR: src provider id={args.src} not found", file=sys.stderr)
            return 2
        if dst is None:
            print(f"ERROR: dst provider id={args.dst} not found", file=sys.stderr)
            return 2

        affected = list(s.scalars(select(Course).where(Course.provider_id == src.id)))
        print(
            f"Will merge provider id={src.id} ({src.name!r}, slug={src.slug!r}) "
            f"INTO id={dst.id} ({dst.name!r}, slug={dst.slug!r})"
        )
        print(f"  Reparent {len(affected)} course(s):")
        for c in affected:
            print(f"    - course id={c.id} slug={c.slug!r} name={c.name!r}")
        print(f"  Then delete provider id={src.id}.")

        if not args.apply:
            print("\n(dry-run — pass --apply to commit)")
            return 0

        if affected:
            s.execute(
                update(Course).where(Course.provider_id == src.id).values(provider_id=dst.id)
            )
        s.flush()
        s.delete(src)
        try:
            s.commit()
        except IntegrityError as exc:
            s.rollback()
            print(f"ERROR: merge failed: {exc.orig}", file=sys.stderr)
            return 3
        print("OK — merge complete.")
    return 0


def _count(col):
    """Tiny shim so we don't import sqlalchemy.func at module top — clearer."""
    from sqlalchemy import func

    return func.count(col)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all providers.").set_defaults(func=_list_providers)

    rename = sub.add_parser("rename", help="Rename a provider in-place.")
    rename.add_argument("id", type=int, help="Provider id (see `list`).")
    rename.add_argument("--name", help="New display name (e.g. 'Palo Alto').")
    rename.add_argument("--slug", help="New slug (lower-case kebab).")
    rename.add_argument("--description", help="New description (use empty string to clear).")
    rename.add_argument("--apply", action="store_true", help="Commit the change.")
    rename.set_defaults(func=_rename)

    merge = sub.add_parser(
        "merge",
        help="Re-parent every course on SRC provider to DST, then delete SRC.",
    )
    merge.add_argument("--src", type=int, required=True, help="Source provider id (will be deleted).")
    merge.add_argument("--dst", type=int, required=True, help="Destination provider id.")
    merge.add_argument("--apply", action="store_true", help="Commit the change.")
    merge.set_defaults(func=_merge)

    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
