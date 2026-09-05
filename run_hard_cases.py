"""Run the context resolver against the 10 conflicting-evidence cases."""

from resolver import resolve_evidence
from hard_cases import CASES


def main():
    print("=" * 72)
    print("Context resolver - 10 conflicting-evidence cases")
    print("=" * 72)
    failed = []
    for spec in CASES:
        result = resolve_evidence(spec["case"])
        ok = (
            result["state_action"] == spec["expected_state_action"]
            and result["financial_action"] == spec["expected_financial_action"]
        )
        print(f"\n[{spec['id']}] {spec['description']}")
        print(f"  expected: {spec['expected_state_action']} / {spec['expected_financial_action']}")
        print(f"  actual:   {result['state_action']} / {result['financial_action']}")
        print(f"  flags:    {result['flags'] or ['none']}")
        print(f"  MATCH: {ok}")
        if not ok:
            failed.append(spec["id"])
    print("\n" + "=" * 72)
    if failed:
        print(f"FAILED: {failed}")
        raise SystemExit(1)
    print(f"ALL {len(CASES)} CASES MATCHED.")


if __name__ == "__main__":
    main()
