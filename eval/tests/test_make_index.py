from eval.schema import Task
from eval.tools.make_index import index_markdown


def t(i, cat, split, chips, status="verified"):
    return Task(id=i, category=cat, split=split, turns=[{"user": "q"}], graders=["exact"], chips=chips, review_status=status)


TASKS = [t("C1-1", "C1", "dev", ["stm32g474"]), t("C1-2", "C1", "test", ["stm32g474"]),
         t("C1-3", "C1", "test", ["esp32"]), t("C6-1", "C6", "dev", ["stm32g474", "esp32"], "needs_human")]


def test_category_table_counts_dev_test_total():
    md = index_markdown(TASKS)
    assert "| C1 | 1 | 2 | 3 |" in md and "| C6 | 1 | 0 | 1 |" in md
    assert "| **Tổng** | 2 | 2 | 4 |" in md


def test_chip_table_counts_each_chip_of_a_task():
    md = index_markdown(TASKS)
    assert "| stm32g474 | 2 | 1 | 3 |" in md       # C1-1, C6-1 dev; C1-2 test
    assert "| esp32 | 1 | 1 | 2 |" in md           # C6-1 dev; C1-3 test


def test_review_status_table_flags_needs_human():
    md = index_markdown(TASKS)
    assert "| needs_human | 1 |" in md and "| verified | 3 |" in md
