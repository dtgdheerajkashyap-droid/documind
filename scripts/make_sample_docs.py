"""Generate the small sample PDFs used by the evaluation dataset.

The documents describe a fictional company so that answers can only come from
the PDFs, never from an LLM's prior knowledge. The generated files are
committed; re-run this script only if you change the content:

    python scripts/make_sample_docs.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

OUT_DIR = Path(__file__).resolve().parent.parent / "backend" / "sample_docs"

HANDBOOK = [
    (
        "1. About Northwind Robotics",
        "Northwind Robotics was founded in 2014 in Pittsburgh, Pennsylvania, by Dr. Elena Vasquez "
        "and Marcus Obi. The company designs autonomous mobile robots for warehouses and "
        "distribution centers. Its flagship product is the Atlas-7 picking robot, which is deployed "
        "at more than 60 customer sites.\n\n"
        "Today Northwind employs about 420 people across three offices: Pittsburgh (headquarters), "
        "Austin, and Rotterdam. Our mission is to take the heavy lifting out of logistics so that "
        "people can focus on skilled work.\n\n"
        "Our core values are Safety First, Build With Care, Own the Outcome, and Learn in Public. "
        "Every new hire completes a two-week onboarding program that includes a full day of robot "
        "safety training on the warehouse floor.",
    ),
    (
        "2. Working Hours and Remote Work",
        "Northwind uses flexible working hours. Every employee is expected to be available during "
        "core hours, from 10:00 to 15:00 in their local time zone. Outside core hours, you may "
        "arrange your schedule with your team.\n\n"
        "We follow a hybrid model. Hybrid employees work from the office at least two days per "
        "week, and Tuesday and Thursday are the company-wide anchor days when teams meet in "
        "person. Fully remote arrangements require written approval from a Vice President.\n\n"
        "To set up a home office, each employee receives a one-time equipment stipend of 600 US "
        "dollars, plus a monthly internet allowance of 40 US dollars, paid through payroll.",
    ),
    (
        "3. Time Off and Leave",
        "Full-time employees receive 25 days of paid time off (PTO) per calendar year. PTO accrues "
        "monthly, starting from your first day of employment. Up to 5 unused PTO days can be "
        "carried over into the next year; carried-over days expire on March 31.\n\n"
        "In addition to PTO, employees receive 10 paid sick days per year. Sick days do not carry "
        "over and are not paid out when you leave the company.\n\n"
        "Northwind offers 16 weeks of fully paid parental leave to all parents, including "
        "adoptive and foster parents. Bereavement leave of up to 5 paid days is available after "
        "the death of a family member.",
    ),
    (
        "4. Expenses and Business Travel",
        "Business expenses must be submitted in the Ledgerly expense tool within 30 days of the "
        "purchase, together with an itemized receipt. Any single purchase above 500 US dollars "
        "needs approval from your manager before it is made.\n\n"
        "Meal expenses during business travel are capped at 75 US dollars per day for domestic "
        "trips and 100 US dollars per day for international trips. Alcohol is not reimbursed.\n\n"
        "Book economy class for flights shorter than six hours. For flights of six hours or more, "
        "employees may book premium economy. Business class is never reimbursed. Hotels should be "
        "booked through the company travel portal.",
    ),
    (
        "5. Security and Conduct",
        "Wear your access badge visibly at all times in Northwind offices and customer sites. "
        "Company laptops use full-disk encryption, and multi-factor authentication is required for "
        "every company account. Store all passwords in the Keyvault password manager.\n\n"
        "If you suspect a security incident, such as a lost laptop or a phishing email you clicked, "
        "report it to the security team at security@northwind.example within one hour. Reporting "
        "quickly is always the right call, and no one is punished for a good-faith report.\n\n"
        "All employees complete phishing-awareness training every quarter.",
    ),
]

MANUAL = [
    (
        "1. Overview and Specifications",
        "The Atlas-7 is an autonomous mobile picking robot for warehouses. It navigates with lidar "
        "and fiducial floor markers and is managed through the Fleet Console web application.\n\n"
        "Key specifications: maximum payload 35 kg; maximum travel speed 2.0 meters per second; "
        "robot weight 118 kg; 48 V lithium iron phosphate (LiFePO4) battery; runtime up to 10 hours "
        "per charge. Fast charging takes the battery from 0 to 80 percent in 45 minutes.\n\n"
        "Operating environment: indoor use only, temperatures from 0 to 40 degrees Celsius, "
        "non-condensing humidity.",
    ),
    (
        "2. Safety",
        "Each Atlas-7 has two red emergency stop buttons, one on each side of the chassis. Pressing "
        "either button cuts power to the drive motors immediately.\n\n"
        "The safety lidar defines two protective zones. When a person or obstacle enters the "
        "slowdown zone, 1.5 meters from the robot, it reduces speed. If anything comes within the "
        "stop zone of 0.5 meters, the robot stops completely until the zone is clear.\n\n"
        "Never ride on the robot or place items on top of the lidar housing. Before any "
        "maintenance, follow the lockout procedure: press an emergency stop, switch off the main "
        "power key, and attach your personal lock to the key switch.",
    ),
    (
        "3. Maintenance",
        "Daily: inspect the drive wheels and casters for damage and debris.\n\n"
        "Weekly: clean the lidar lens with a dry microfiber cloth. Do not use solvents.\n\n"
        "Monthly: run the battery calibration routine from the Fleet Console.\n\n"
        "Every 2,000 operating hours: replace both drive wheels. Wheel wear beyond this point "
        "increases localization errors.\n\n"
        "Firmware updates are distributed through the Fleet Console and should be installed "
        "during a scheduled maintenance window.",
    ),
    (
        "4. Troubleshooting and Error Codes",
        "E101 - Lidar obstruction: the lidar view is blocked. Clean the lens and remove any objects "
        "near the sensor.\n\n"
        "E204 - Battery temperature high: move the robot to a cooler area and let it rest for 20 "
        "minutes before resuming operation.\n\n"
        "E310 - Wheel motor stall: check the wheels for debris such as shrink wrap or straps, then "
        "clear the error in the Fleet Console.\n\n"
        "E450 - Lost localization: the robot no longer knows its position. Manually drive it to "
        "the nearest fiducial marker and select Re-localize in the Fleet Console.\n\n"
        "If an error persists, contact Northwind support at +1-412-555-0199.",
    ),
]


def write_pdf(path: Path, title: str, sections: list[tuple[str, str]]) -> None:
    doc = pymupdf.open()
    for heading, body in sections:
        page = doc.new_page()  # US Letter-ish default (A4)
        page.insert_text((72, 60), title, fontsize=9, color=(0.4, 0.4, 0.4))
        page.insert_text((72, 100), heading, fontsize=16)
        page.insert_textbox(pymupdf.Rect(72, 120, 523, 780), body, fontsize=11, lineheight=1.4)
    doc.set_metadata({"title": title, "author": "DocuMind sample data"})
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_pdf(OUT_DIR / "northwind_handbook.pdf", "Northwind Robotics Employee Handbook", HANDBOOK)
    write_pdf(OUT_DIR / "atlas7_manual.pdf", "Atlas-7 Operator Manual", MANUAL)
    print(f"Wrote sample PDFs to {OUT_DIR}")


if __name__ == "__main__":
    main()
