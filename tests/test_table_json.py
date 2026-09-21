"""The shared JSON spelling refuses values JSON cannot represent."""

import pytest

from spicy_docs.schemas.tables import TableContractError, json_column


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_nested_nonfinite_json_is_a_table_refusal(number: float) -> None:
    with pytest.raises(TableContractError, match="non-finite"):
        json_column({"evidence": [{"signal": number}]})


def test_finite_json_keeps_its_exact_existing_spelling() -> None:
    assert json_column({"z": [None, True, False, -0.0, 1.25, 1e20], "a": "é\n"}) == (
        '{"a":"\\u00e9\\n","z":[null,true,false,-0.0,1.25,1e+20]}'
    )


def test_circular_json_is_a_table_refusal() -> None:
    values: list[object] = []
    values.append(values)
    with pytest.raises(TableContractError, match="circular"):
        json_column(values)
