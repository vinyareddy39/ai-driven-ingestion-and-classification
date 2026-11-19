import sys
from app.core.config import get_pipeline_config

def verify_and_print_config_consistency():
    cfg = get_pipeline_config()
    high_floor = cfg.compliance_floors.high_risk_floor if cfg.compliance_floors else 0.95
    low_floor = cfg.compliance_floors.low_risk_floor if cfg.compliance_floors else 0.90

    print("="*80)
    print("CONFIG CONSISTENCY AND COMPLIANCE FLOOR AUDIT")
    print("="*80)
    print(f"Mandatory Compliance Floors: Low-Risk = {low_floor:.2f}, High-Risk = {high_floor:.2f}\n")
    print(f"{'Class Name':<18} | {'Risk':<6} | {'Default':<7} | {'Tuned':<7} | {'Effective':<9} | {'Floor':<6} | Status")
    print("-" * 75)

    violations = []
    for c_name, c_cfg in cfg.classes.items():
        is_high = c_cfg.risk == "high"
        floor = high_floor if is_high else low_floor
        effective = c_cfg.tuned_threshold
        status = "PASS" if effective >= floor else "FAIL_BELOW_FLOOR"

        print(f"{c_name:<18} | {c_cfg.risk:<6} | {c_cfg.default_threshold:<7.2f} | {c_cfg.tuned_threshold:<7.2f} | {effective:<9.2f} | {floor:<6.2f} | {status}")

        if effective < floor:
            violations.append(f"{c_name}: effective {effective:.2f} < floor {floor:.2f}")

    if violations:
        msg = f"FATAL CONFIG ERROR: {len(violations)} classes have thresholds below their mandatory compliance floor:\n" + "\n".join(violations)
        print("\n" + msg, file=sys.stderr)
        raise ValueError(msg)

    print("\nALL CLASSES COMPLIANT: Zero thresholds below compliance floors.")

if __name__ == "__main__":
    verify_and_print_config_consistency()
