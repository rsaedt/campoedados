from __future__ import annotations

import argparse
import sys

from app.core.database import SessionLocal
from app.services.modules import DEFAULT_MODULES
from app.services.onboarding import OnboardingError, OnboardingUnit, onboard_organization


def _unit(value: str) -> OnboardingUnit:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Use --unit CODIGO=Nome da unidade")
    code, name = value.split("=", 1)
    code = code.strip()
    name = name.strip()
    if not code or not name:
        raise argparse.ArgumentTypeError("Use --unit CODIGO=Nome da unidade")
    return OnboardingUnit(code=code, name=name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cria uma organização do Campo e Dados sem usar ENV de cliente."
    )
    parser.add_argument("--org-name", required=True, help="Nome da organização/empresa.")
    parser.add_argument("--org-slug", required=True, help="Slug único, ex.: agro-homolog.")
    parser.add_argument("--admin-name", required=True, help="Nome do administrador inicial.")
    parser.add_argument(
        "--admin-email",
        default=None,
        help="E-mail do administrador. Opcional; pode ser vinculado depois.",
    )
    parser.add_argument(
        "--unit",
        action="append",
        type=_unit,
        required=True,
        help="Unidade no formato CODIGO=Nome. Repita para várias unidades.",
    )
    parser.add_argument(
        "--module",
        action="append",
        choices=sorted(DEFAULT_MODULES),
        required=True,
        help="Módulo contratado. Repita para combinar módulos.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with SessionLocal() as session:
        try:
            result = onboard_organization(
                session,
                organization_name=args.org_name,
                organization_slug=args.org_slug,
                admin_name=args.admin_name,
                admin_email=args.admin_email,
                units=args.unit,
                modules=args.module,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    print("onboarding: OK")
    print(f"organization={result.organization.slug}")
    print(f"admin_user_id={result.admin_user.id}")
    print(f"admin_membership_id={result.admin_membership.id}")
    print("units=" + ",".join(unit.code for unit in result.units))
    print("modules=" + ",".join(result.enabled_modules))
    print("")
    print("ADMIN TOKEN — copie agora; o valor bruto não é armazenado e não será exibido novamente:")
    print(result.raw_admin_token)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OnboardingError, ValueError) as exc:
        print(f"onboarding failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
