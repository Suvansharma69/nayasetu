from src.api.dates import find_dates


def dates(text):
    return [d["date"] for d in find_dates(text)["dates"]]


def test_common_indian_forms():
    assert dates("On 15 August 2024 the accused took the bike.") == ["2024-08-15"]
    assert dates("on the 15th of Aug, 2024") == ["2024-08-15"]
    assert dates("on August 15, 2024") == ["2024-08-15"]
    assert dates("dated 2024-08-15") == ["2024-08-15"]


def test_numeric_dates_are_day_first():
    assert dates("on 05/08/2024") == ["2024-08-05"]
    assert dates("on 05-08-2024 and again on 05.08.2024") == ["2024-08-05"]


def test_several_distinct_dates_are_all_reported():
    assert dates("The theft was on 30 June 2024; the FIR was lodged on 2 July 2024.") == \
        ["2024-06-30", "2024-07-02"]


def test_invalid_and_missing():
    assert dates("on 31/02/2024") == []
    assert dates("The accused took Rs 1,85,000 from 23 people.") == []
    assert dates("Section 303(2) BNS, 2023") == []


def test_month_without_day_is_not_a_date():
    r = find_dates("Sometime in August 2024 the accused cheated her.")
    assert r["dates"] == [] and r["month_only"] == ["August 2024"]
    assert find_dates("on 15 August 2024")["month_only"] == []
