import pytest

from tracker.extractor import extract_expense   

def test_extractor_cases():
    prompts = ["pizza", "random text", "coffee 3.5 at Starbucks yesterday", "paid 15 euros"]
    resp1 = extract_expense(prompts[0])
    assert isinstance(resp1, ValueError)
    resp2 = extract_expense(prompts[1])
    assert isinstance(resp2, ValueError)
    resp3 = extract_expense(prompts[2])
    assert resp3["amount"] == 3.5
    assert resp3["merchant"] == "Starbucks"
    assert resp3["category"] == "Food & Drink"
    assert resp3["date"] == "2026-04-18"
    resp4 = extract_expense(prompts[3])
    assert resp4["amount"] == 15
    assert resp4["merchant"] == "Unknown"   
    assert resp4["category"] == "Other"
    assert resp4["date"] == None