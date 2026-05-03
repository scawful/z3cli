from pathlib import Path

from protocol.asm_symbol_bridge import AsmSymbolBridge


def test_long_address_query_preserves_bank_zeroes(tmp_path: Path):
    (tmp_path / "symbols.mlb").write_text(
        "\n".join(
            [
                "SnesWorkRam:7FFD5C:GANONWARPXL:",
                "SnesPrgRom:00FFD5:ResetVector:",
            ]
        ),
        encoding="utf-8",
    )

    bridge = AsmSymbolBridge(tmp_path)

    hits = bridge._search("$00FFD5")

    assert any("00FFD5:ResetVector" in hit for hit in hits)
    assert not any("7FFD5C" in hit for hit in hits)
