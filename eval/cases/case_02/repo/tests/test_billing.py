from invoicing.billing import apply_discount, calculate_total, line_item_total


def test_apply_discount():
    assert apply_discount(100.0, 20) == 80.0


def test_line_item_total():
    assert line_item_total(9.5, 3) == 28.5


def test_calculate_total_applies_tax_rate():
    assert calculate_total(100.0, 0.20) == 120.0


def test_calculate_total_zero_tax():
    assert calculate_total(50.0, 0) == 50.0
