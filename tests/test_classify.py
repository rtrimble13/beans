from datetime import date, timedelta

import pytest

from beans import classify
from beans.classify import (
    COLUMN,
    HISTORY,
    NONE,
    RULE,
    Classifier,
    key_similarity,
    merchant_key,
    write_prepared_csv,
)
from beans.importer import import_csv
from beans.matching import read_statement
from beans.utils import BeansError
from tests.conftest import post


def checking(led):
    return led.find_account("Assets:Checking")


def teach(led, description, account, times=1, start=date(2026, 1, 1)):
    """Give the ledger a history of categorizing `description` one way."""
    for i in range(times):
        post(led, start + timedelta(days=i), description,
             (account, 1000), ("Assets:Checking", -1000))


def write_csv(tmp_path, rows, name="in.csv",
              header="date,description,amount,category"):
    path = tmp_path / name
    path.write_text(header + "\n" + "\n".join(rows) + "\n")
    return str(path)


# -- the merchant key --------------------------------------------------------


def test_merchant_key_strips_every_digit_run():
    """Unlike matching.normalize, which keeps single digits because a
    number can be a transaction's identity, merchant keys drop them all —
    otherwise one shop fragments across dozens of buckets."""
    assert merchant_key("AMAZON MKTPLACE 3") == "amazon mktplace"
    assert merchant_key("AMAZON MKTPLACE 12") == "amazon mktplace"
    assert merchant_key("WHOLE FOODS MARKET #412") == "whole foods market"
    assert merchant_key("") == ""


def test_key_similarity_requires_a_real_overlap_to_contain():
    assert key_similarity("shell oil", "shell oil") == 1.0
    assert key_similarity("shell", "shell oil company") == 1.0
    # too short to sweep up everything containing it
    assert key_similarity("abc", "abc corporation") < 1.0
    assert key_similarity("", "anything") == 0.0


# -- sources and their priority ----------------------------------------------


def test_an_existing_category_wins_over_everything(led):
    teach(led, "WHOLE FOODS MARKET #412", "Expenses:Food:Groceries", 20)
    led.add_import_rule("WHOLE FOODS", led.find_account("Expenses:Other"))
    found = Classifier(led, checking(led)).suggest(
        "WHOLE FOODS MARKET #412", category="Expenses:Food:Dining")
    assert found.source == COLUMN
    assert found.account == "Expenses:Food:Dining"
    assert found.confidence == 1.0


def test_a_rule_beats_history_because_it_is_explicit(led):
    """History is descriptive, a rule is prescriptive — so a standing
    intent overrides what you happened to do before."""
    teach(led, "AMAZON MKTPLACE 1", "Expenses:Shopping", 30)
    led.add_import_rule("AMAZON", led.find_account("Expenses:Other"))
    found = Classifier(led, checking(led)).suggest("AMAZON MKTPLACE 9")
    assert found.source == RULE
    assert found.account == "Expenses:Other"
    assert found.confidence == 1.0


def test_history_answers_when_no_rule_does(led):
    teach(led, "WHOLE FOODS MARKET #412", "Expenses:Food:Groceries", 20)
    found = Classifier(led, checking(led)).suggest("WHOLE FOODS MARKET #781")
    assert found.source == HISTORY
    assert found.account == "Expenses:Food:Groceries"
    assert found.basis == "20 prior"


def test_an_unknown_merchant_gets_no_guess(led):
    teach(led, "WHOLE FOODS MARKET #412", "Expenses:Food:Groceries", 20)
    found = Classifier(led, checking(led)).suggest("TOTALLY NEW VENDOR LLC")
    assert found.source == NONE
    assert found.account is None and found.confidence == 0.0


def test_a_fresh_ledger_suggests_nothing_from_history(led):
    """The cold-start case: this is why rules still exist."""
    classifier = Classifier(led, checking(led))
    assert classifier.history_size == 0
    assert classifier.suggest("WHOLE FOODS MARKET #412").source == NONE


# -- confidence --------------------------------------------------------------


def test_confidence_rises_with_the_weight_of_evidence(led):
    """A single unanimous prior must not look as certain as forty."""
    day = date(2026, 1, 1)
    for merchant, n in (("MERCHANT A", 1), ("MERCHANT B", 3),
                        ("MERCHANT C", 10), ("MERCHANT D", 40)):
        teach(led, merchant, "Expenses:Food:Groceries", n, start=day)
        day += timedelta(days=n + 1)
    classifier = Classifier(led, checking(led))
    scores = [classifier.suggest(m).confidence
              for m in ("MERCHANT A", "MERCHANT B", "MERCHANT C",
                        "MERCHANT D")]
    assert scores == sorted(scores)          # strictly more evidence
    assert scores[0] < 0.5 < scores[-1]      # and it spans the range


def test_a_split_merchant_scores_lower_and_shows_the_split(led):
    teach(led, "AMAZON MKTPLACE 1", "Expenses:Shopping", 14)
    teach(led, "AMAZON MKTPLACE 2", "Expenses:Other", 6,
          start=date(2026, 6, 1))
    found = Classifier(led, checking(led)).suggest("AMAZON MKTPLACE 99")
    assert found.account == "Expenses:Shopping"   # the majority
    assert found.confidence < 0.75                # but not confidently
    assert "20 prior" in found.basis
    assert "14 Shopping" in found.basis and "6 Other" in found.basis


def test_thin_and_conflicted_evidence_are_distinguishable(led):
    """Two rows can score alike for opposite reasons — the basis is what
    tells them apart, which is why both are always emitted."""
    teach(led, "UNITED AIRLINES 1", "Expenses:Other", 3)
    teach(led, "AMAZON MKTPLACE 1", "Expenses:Shopping", 14,
          start=date(2026, 3, 1))
    teach(led, "AMAZON MKTPLACE 2", "Expenses:Food:Dining", 6,
          start=date(2026, 6, 1))
    classifier = Classifier(led, checking(led))
    thin = classifier.suggest("UNITED AIRLINES 900")
    split = classifier.suggest("AMAZON MKTPLACE 99")
    assert abs(thin.confidence - split.confidence) < 0.2   # alike
    assert thin.basis == "3 prior"                          # but not alike
    assert "/" in split.basis


def test_since_limits_what_history_is_learned_from(led):
    teach(led, "SOME MERCHANT", "Expenses:Other", 10,
          start=date(2026, 1, 1))
    teach(led, "SOME MERCHANT", "Expenses:Food:Groceries", 4,
          start=date(2026, 9, 1))
    recent = Classifier(led, checking(led), since=date(2026, 8, 1))
    assert recent.history_size == 4
    assert recent.suggest("SOME MERCHANT").account == \
        "Expenses:Food:Groceries"


# -- what history is learned from --------------------------------------------


def test_multi_leg_splits_are_not_learned_from(led):
    """A three-way split has no single counter-account, so it is left out
    rather than guessed at."""
    post(led, date(2026, 1, 1), "COSTCO WHOLESALE",
         ("Expenses:Food:Groceries", 15000), ("Expenses:Other", 5144),
         ("Assets:Checking", -20144))
    assert Classifier(led, checking(led)).history_size == 0


def test_voided_transactions_are_not_learned_from(led):
    teach(led, "SOME MERCHANT", "Expenses:Other", 3)
    for txn in led.transactions():
        led.void_transaction(txn.id)
    assert Classifier(led, checking(led)).history_size == 0


def test_history_is_scoped_to_the_target_account(led):
    post(led, date(2026, 1, 1), "SOME MERCHANT",
         ("Expenses:Other", 1000), ("Liabilities:Credit Card", -1000))
    assert Classifier(led, checking(led)).history_size == 0
    card = led.find_account("Liabilities:Credit Card")
    assert Classifier(led, card).history_size == 1


# -- the prepared file -------------------------------------------------------


def test_prepared_file_round_trips_through_import(led, tmp_path):
    teach(led, "WHOLE FOODS MARKET #412", "Expenses:Food:Groceries", 20)
    path = write_csv(tmp_path, ["2026-07-01,WHOLE FOODS MARKET #781,-86.40,"])
    rows = read_statement(path, 2)
    account = checking(led)
    out = str(tmp_path / "prepared.csv")
    assert write_prepared_csv(led, Classifier(led, account), rows, out) == 1

    text = open(out).read()
    assert text.splitlines()[0] == (
        "date,description,amount,category,confidence,basis")
    assert "Expenses:Food:Groceries" in text
    # the extra columns ride along and `import` simply ignores them
    result = import_csv(led, out, account)
    assert len(result["imported"]) == 1
    assert result["imported"][0]["counter"] == "Expenses:Food:Groceries"


def test_prepared_file_is_re_runnable_without_losing_decisions(led,
                                                               tmp_path):
    path = write_csv(tmp_path, ["2026-07-05,MYSTERY LLC,-31.00,"])
    account = checking(led)
    out = tmp_path / "prepared.csv"
    write_prepared_csv(led, Classifier(led, account),
                       read_statement(path, 2), str(out))
    assert ",,0.00,no match" in out.read_text()
    # a human fills the blank in
    out.write_text(out.read_text().replace(
        "-31.00,,0.00,no match", "-31.00,Expenses:Other,0.00,no match"))
    again = read_statement(str(out), 2)
    found = Classifier(led, account).suggest(again[0].description,
                                             again[0].category)
    assert found.source == COLUMN and found.account == "Expenses:Other"


def test_prepared_file_refuses_to_clobber_an_edited_one(led, tmp_path):
    path = write_csv(tmp_path, ["2026-07-05,MYSTERY LLC,-31.00,"])
    rows = read_statement(path, 2)
    out = str(tmp_path / "prepared.csv")
    write_prepared_csv(led, Classifier(led, checking(led)), rows, out)
    with pytest.raises(BeansError, match="already exists"):
        write_prepared_csv(led, Classifier(led, checking(led)), rows, out)
    write_prepared_csv(led, Classifier(led, checking(led)), rows, out,
                       force=True)


def test_report_counts_every_source_and_sorts_least_certain_first(led,
                                                                  tmp_path):
    teach(led, "WHOLE FOODS MARKET #412", "Expenses:Food:Groceries", 20)
    led.add_import_rule("CITY POWER",
                        led.find_account("Expenses:Housing:Utilities"))
    path = write_csv(tmp_path, [
        "2026-07-01,WHOLE FOODS MARKET #781,-86.40,",
        "2026-07-02,CITY POWER & LIGHT,-118.40,",
        "2026-07-03,MYSTERY LLC,-31.00,",
        "2026-07-04,KNOWN ALREADY,-9.00,Expenses:Other",
    ])
    account = checking(led)
    classifier = Classifier(led, account)
    rows = read_statement(path, 2)
    data = classify.categorize_report(led, account, classifier, rows, path)
    assert data["summary"] == {"rows": 4, "column": 1, "rule": 1,
                               "history": 1, "unresolved": 1}
    text = classify.render_categorize(data, 2, "$")
    # the row needing a decision is listed before the certain ones
    assert text.index("MYSTERY LLC") < text.index("KNOWN ALREADY")
    assert "not a probability" in text


# -- the nearest-merchant fallback -------------------------------------------


def test_a_near_miss_still_finds_the_merchant(led):
    """A descriptor that drifts slightly still resolves, and says it was
    a near match rather than an exact one."""
    teach(led, "STARBUCKS STORE", "Expenses:Food:Dining", 10)
    found = Classifier(led, checking(led)).suggest("STARBUKS STORE")
    assert found.source == HISTORY
    assert found.account == "Expenses:Food:Dining"
    assert found.basis.startswith("~")


def test_a_near_miss_scores_below_the_same_merchant_seen_exactly(led):
    teach(led, "STARBUCKS STORE", "Expenses:Food:Dining", 10)
    classifier = Classifier(led, checking(led))
    exact = classifier.suggest("STARBUCKS STORE #755")
    near = classifier.suggest("STARBUKS STORE")
    assert near.confidence < exact.confidence


def test_an_unrelated_name_is_not_dragged_to_the_nearest_merchant(led):
    teach(led, "STARBUCKS STORE", "Expenses:Food:Dining", 10)
    assert Classifier(led, checking(led)).suggest(
        "HARBOR POINT VETERINARY").source == NONE


def test_containment_picks_the_most_specific_merchant(led):
    teach(led, "SHELL", "Expenses:Other", 5)
    teach(led, "SHELL OIL COMPANY", "Expenses:Transportation", 5,
          start=date(2026, 6, 1))
    found = Classifier(led, checking(led)).suggest("SHELL OIL COMPANY 57422")
    assert found.account == "Expenses:Transportation"


def test_the_same_ledger_always_gives_the_same_answer(led):
    """Ties must not depend on dict or row ordering — this is accounting."""
    for merchant in ("ALPHA VENDOR", "ALPHA VENDORS", "ALPHA VENDOR CO"):
        teach(led, merchant, "Expenses:Other", 4,
              start=date(2026, 1, 1) + timedelta(days=len(merchant)))
    answers = {Classifier(led, checking(led)).suggest("ALPHA VENDOR X").basis
               for _ in range(5)}
    assert len(answers) == 1
