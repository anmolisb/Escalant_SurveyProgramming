"""Put the team and the corpus into a fresh database.

Run once. Safe to run again: everything is an upsert, so it will not
duplicate anyone or lose a finding.
"""
from pathlib import Path

import store

TEAM = [
    ("anoop.kumar@escalent.co",  "Anoop Kumar", "AK", "QA tester"),
    ("raveena.s@escalent.co",    "Raveena S",   "RS", "Survey programmer"),
    ("sanskar.m@escalent.co",    "Sanskar M",   "SM", "QA manager"),
    ("atishi.t@escalent.co",     "Atishi T",    "AT", "Project lead"),
    ("anmol.g@escalent.co",      "Anmol G",     "AN", "Survey programmer"),
]

CORPUS = [
    ("C01_chronic_care_patient_journey",    "C01", "Complex"),
    ("C02_automotive_purchase_journey",     "C02", "Complex"),
    ("C04_retail_banking_brand_tracker",    "C04", "Complex"),
    ("M01_mobile_network_experience",       "M01", "Medium"),
    ("M02_electric_vehicle_consideration",  "M02", "Medium"),
    ("M03_insurance_claims_experience",     "M03", "Medium"),
    ("M05_employee_hybrid_work_experience", "M05", "Medium"),
    ("M06_digital_wallet_usage",            "M06", "Medium"),
    ("S01_campus_cafeteria_experience",     "S01", "Pilot"),
    ("F01_snack_bar_concept_test_SYNTHETIC", "F01", "Held back"),
    ("F02_streaming_brand_tracker_SYNTHETIC", "F02", "Held back"),
]

RULES = [
    ("blank",      "Every compulsory question refuses a blank"),
    ("whitespace", "Every compulsory question refuses spaces alone"),
    ("endings",    "Each ending shows its own wording"),
    ("punctuation", "Open text accepts punctuation"),
    ("carried",    "Carried-forward options match by code"),
    ("quota_cell", "Quotas counted per cell, not across"),
]


def main(db=store.DB_PATH):
    store.setup(db)
    for email, name, initials, role in TEAM:
        # The starting password is the same for everyone and is meant to be
        # changed. It is stored salted and hashed, never in the clear.
        store.add_person(email, name, initials, role, "escalent", path=db)
    for run_name, code, tier in CORPUS:
        store.upsert_questionnaire(
            run_name, code=code, tier=tier,
            held_back=1 if tier == "Held back" else 0, path=db)
    with store.connect(db) as conn:
        for key, name in RULES:
            conn.execute(
                "INSERT OR IGNORE INTO house_rule (key,name) VALUES (?,?)",
                (key, name))
    print(f"  {len(TEAM)} people, {len(CORPUS)} questionnaires, "
          f"{len(RULES)} house rules")
    print(f"  database at {Path(db).resolve()}")
    print("  everyone's starting password is: escalent")


if __name__ == "__main__":
    main()
