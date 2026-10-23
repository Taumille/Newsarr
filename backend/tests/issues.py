"""Issue catalog tests: schedule generation, scanning, covers and statuses.

Run with:  PYTHONPATH=. .venv/bin/python tests/issues.py
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="newsarr-issues-"))
os.environ["NEWSARR_DATA_DIR"] = str(TMP / "data")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import Release  # noqa: E402
from app.services.issues import (  # noqa: E402
    extract_date_from_filename,
    generate_issue_dates,
    release_matches_issue,
)

LIBRARY = TMP / "library"
CANARD = LIBRARY / "le-canard-enchaine"

# A 1x1 PNG (enough to exercise upload/serve; content is not re-encoded).
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"
)


def main() -> None:
    failures: list[str] = []

    def check(label: str, condition: bool, extra: object = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label} {extra if not condition else ''}")
        if not condition:
            failures.append(label)

    print("Date helpers...")
    check(
        "weekly schedule",
        generate_issue_dates("weekly", 2, date(2020, 1, 1), date(2020, 1, 31))
        == [date(2020, 1, d) for d in (1, 8, 15, 22, 29)],
    )
    check(
        "weekly aligns to weekday",
        generate_issue_dates("weekly", 2, date(2020, 1, 2), date(2020, 1, 15))
        == [date(2020, 1, 8), date(2020, 1, 15)],
    )
    check(
        "monthly clamps short months",
        generate_issue_dates("monthly", None, date(2021, 1, 31), date(2021, 3, 31))
        == [date(2021, 1, 31), date(2021, 2, 28), date(2021, 3, 31)],
    )
    for name, expected in (
        ("Paper 2020-01-08.pdf", date(2020, 1, 8)),
        ("Paper 08-01-2020.pdf", date(2020, 1, 8)),
        ("Paper 20200108.pdf", date(2020, 1, 8)),
        ("Paper 8 January 2020.pdf", date(2020, 1, 8)),
        ("Paper 8 janvier 2020.pdf", date(2020, 1, 8)),
    ):
        check(f"date from {name!r}", extract_date_from_filename(name) == expected)
    release = Release(
        title="Le Canard Enchaîné 2020-01-08",
        publish_date=datetime(2026, 10, 21, tzinfo=timezone.utc),
    )
    check("title date beats upload date", release_matches_issue(release, date(2020, 1, 8)))
    check("wrong date does not match", not release_matches_issue(release, date(2020, 1, 15)))

    with TestClient(app) as client:
        r = client.put("/api/v1/settings", json={"library_root": str(LIBRARY)})
        check("library root saved", r.status_code == 200, r.text)

        print("Creating a weekly publication (Le Canard Enchaîné, Wednesdays since 2020)...")
        r = client.post(
            "/api/v1/publications",
            json={
                "title": "Le Canard Enchaîné",
                "frequency": "weekly",
                "weekday": 2,  # Wednesday (Monday=0)
                "start_date": "2020-01-01",
                "categories": "7010",
            },
        )
        check("publication created", r.status_code == 201, r.text)
        publication = r.json()
        pub_id = publication["id"]
        check("calendar generated on create", publication["issue_total"] > 250, publication)
        check("all generated issues are missing", publication["issue_missing"] == publication["issue_total"])
        check("cover flag false", publication["has_cover"] is False)

        print("Checking generated dates and weekday alignment...")
        r = client.get(
            f"/api/v1/publications/{pub_id}/issues?from_date=2020-01-01&to_date=2020-01-31"
        )
        check("issue list ok", r.status_code == 200, r.text)
        payload = r.json()
        january = [date.fromisoformat(i["issue_date"]) for i in payload["issues"]]
        check("January has five Wednesdays", len(january) == 5, january)
        check("first issue is 2020-01-01", january[-1] == date(2020, 1, 1), january)
        check("all issues are Wednesdays", all(d.weekday() == 2 for d in january), january)

        print("Scanning the library folder...")
        CANARD.mkdir(parents=True)
        (CANARD / "Le Canard Enchaîné - 2020-01-08.pdf").write_bytes(b"%PDF-1.4 owned\n")
        r = client.post(f"/api/v1/publications/{pub_id}/issues/scan")
        check("scan ok", r.status_code == 200, r.text)
        check("one file matched", r.json()["matched"] == 1, r.json())
        check("one issue owned", r.json()["owned"] == 1, r.json())

        r = client.get(f"/api/v1/publications/{pub_id}/issues?status=owned")
        owned = r.json()["issues"]
        check("owned issue listed", len(owned) == 1, owned)
        check("owned date matches file", owned[0]["issue_date"] == "2020-01-08", owned)
        check("file path stored", owned[0]["file_path"].endswith("2020-01-08.pdf"), owned[0])

        print("Manual status changes...")
        issue_id = owned[0]["id"]
        r = client.patch(f"/api/v1/issues/{issue_id}", json={"status": "expected"})
        check("mark missing", r.status_code == 200 and r.json()["status"] == "expected", r.text)
        r = client.patch(f"/api/v1/issues/{issue_id}", json={"status": "ignored"})
        check("mark ignored", r.json()["status"] == "ignored", r.text)

        print("Regenerating must not delete owned/ignored issues...")
        r = client.post(f"/api/v1/publications/{pub_id}/issues/generate")
        check("regenerate ok", r.status_code == 200, r.text)
        r = client.get(f"/api/v1/publications/{pub_id}/issues?status=ignored")
        check("ignored issue kept", r.json()["total"] == 1, r.json())

        print("Cover upload / serve / delete...")
        r = client.post(
            f"/api/v1/publications/{pub_id}/cover",
            files={"file": ("cover.png", PNG, "image/png")},
        )
        check("cover uploaded", r.status_code == 200 and r.json()["has_cover"] is True, r.text)
        r = client.get(f"/api/v1/publications/{pub_id}/cover")
        check("cover served as png", r.status_code == 200 and r.headers["content-type"].startswith("image/png"), r.headers)
        r = client.post(
            f"/api/v1/publications/{pub_id}/cover",
            files={"file": ("notes.txt", b"nope", "text/plain")},
        )
        check("bad cover type rejected", r.status_code == 400, r.text)
        r = client.delete(f"/api/v1/publications/{pub_id}/cover")
        check("cover removed", r.status_code == 200 and r.json()["has_cover"] is False, r.text)

        print("Deleting the publication removes its issues...")
        r = client.delete(f"/api/v1/publications/{pub_id}")
        check("publication deleted", r.status_code == 204, r.text)
        r = client.get(f"/api/v1/issues/{issue_id}")
        check("issue gone", r.status_code == 404, r.text)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        raise SystemExit(1)
    print("All issue-catalog checks passed ✅")


if __name__ == "__main__":
    main()
