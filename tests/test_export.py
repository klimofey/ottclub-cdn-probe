"""Exporting the journal for spreadsheets and scripts."""

from cdnprobe.storage import CSV_COLUMNS, csv_rows


def record(at, cdn="Испания", nets=("1.2.3.0/24", "4.5.6.0/24")):
    return {"at": at, "cdn": cdn, "cdn_value": "20", "confirmed": True,
            "ratio_avg": 5.37, "ratio_worst": 4.77, "risk_share": 0.0,
            "networks": list(nets)}


class TestCsvRows:
    def test_header_comes_first(self):
        assert csv_rows([])[0] == list(CSV_COLUMNS)

    def test_rows_are_ordered_oldest_first(self):
        rows = csv_rows([record("2026-09-06T10:00:00"), record("2026-09-05T10:00:00")])
        assert rows[1][0] < rows[2][0]

    def test_networks_collapse_into_one_cell(self):
        """A variable column count would break every spreadsheet import."""
        row = csv_rows([record("2026-09-06T10:00:00")])[1]
        assert len(row) == len(CSV_COLUMNS)
        assert row[-1] == "1.2.3.0/24 4.5.6.0/24"

    def test_shape_holds_when_a_round_found_nothing(self):
        row = csv_rows([record("2026-09-06T10:00:00", nets=())])[1]
        assert len(row) == len(CSV_COLUMNS)
        assert row[-1] == ""

    def test_booleans_are_written_as_words(self):
        rows = csv_rows([{**record("2026-09-06T10:00:00"), "confirmed": False}])
        assert rows[1][3] == "false"

    def test_missing_fields_do_not_raise(self):
        row = csv_rows([{"at": "2026-09-06T10:00:00", "cdn": "X"}])[1]
        assert len(row) == len(CSV_COLUMNS)
