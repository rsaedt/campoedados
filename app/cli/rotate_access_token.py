from __future__ import annotations

import argparse
import sys

from app.core.database import SessionLocal
from app.services.admin_ops import AdminOperationError, rotate_access_token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rotaciona token de acesso de forma controlada e auditada."
    )
    parser.add_argument("--org-slug", required=True, help="Slug da organização.")
    parser.add_argument(
        "--membership-id",
        default=None,
        help="Vínculo a rotacionar. Se omitido, exige exatamente um admin ativo.",
    )
    parser.add_argument(
        "--label",
        default="admin-rotation",
        help="Rótulo auditável do novo token.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with SessionLocal() as session:
        try:
            result = rotate_access_token(
                session,
                organization_slug=args.org_slug,
                membership_id=args.membership_id,
                label=args.label,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    print("token rotation: OK")
    print(f"organization_id={result.organization_id}")
    print(f"membership_id={result.membership_id}")
    print(f"revoked_token_count={result.revoked_token_count}")
    print(f"new_token_id={result.new_token_id}")
    print("")
    print("NOVO TOKEN — copie agora; o valor bruto não é armazenado e não será exibido novamente:")
    print(result.raw_token)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AdminOperationError, ValueError) as exc:
        print(f"token rotation failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
