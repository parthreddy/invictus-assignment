# Results — 40 sample messages

Run via `make replay` (real gpt-4o-mini). One message (m-1003) arrives twice and is deduped to a single work order.

| # | msg | shop | status | services | total | flags |
|---|-----|------|--------|----------|-------|-------|
| 1 | m-1001 | downtown | OPEN | TUNE_BASICx1 | $65.00 |  |
| 2 | m-1002 | northside | OPEN | FLAT_FIXx1 | $15.00 |  |
| 4 | m-1004 | downtown | OPEN | BRAKE_PADSx1, BRAKE_BLEEDx1 | $75.00 |  |
| 5 | m-1005 | northside | OPEN | BRAKE_ADJUSTx1, GEAR_ADJUSTx1 | $43.00 |  |
| 6 | m-1006 | lakeshore | OPEN | WHEEL_TRUEx1 | $30.00 |  |
| 7 | m-1007 | downtown | OPEN | TUNE_FULLx1 | $185.00 |  |
| 8 | m-1008 | northside | OPEN | EBIKE_DIAGx1 | $60.00 | inspect |
| 9 | m-1009 | downtown | OPEN | TIRE_REPLACEx2 | $40.00 | wrong-shop |
| 10 | m-1010 | lakeshore | OPEN | CHAIN_REPLACEx1 | $45.00 |  |
| 11 | m-1011 | downtown | OPEN | BRAKE_BLEEDx1 | $40.00 |  |
| 12 | m-1012 | northside | OPEN | GENERAL_INSPECTx1 | $25.00 | inspect |
| 13 | m-1013 | lakeshore | OPEN | FLAT_FIXx2, TIRE_REPLACEx1 | $50.00 |  |
| 14 | m-1003 | lakeshore | OPEN | CHAIN_REPLACEx1, GEAR_ADJUSTx1 | $70.00 |  |
| 15 | m-1015 | downtown | OPEN | TUNE_BASICx1 | $65.00 |  |
| 16 | m-1016 | northside | OPEN | GEAR_ADJUSTx1 | $25.00 |  |
| 17 | m-1017 | lakeshore | OPEN | BRAKE_ADJUSTx2 | $36.00 |  |
| 18 | m-1018 | downtown | INFO_ONLY | — | — |  |
| 19 | m-1019 | northside | OPEN | BRAKE_ADJUSTx1, WHEEL_TRUEx1 | $48.00 |  |
| 20 | m-1020 | lakeshore | NEEDS_INFO | — | — |  |
| 21 | m-1021 | downtown | OPEN | TIRE_REPLACEx1 | $20.00 |  |
| 22 | m-1022 | northside | OPEN | EBIKE_DIAGx1 | $60.00 | inspect |
| 23 | m-1023 | lakeshore | OPEN | TUNE_BASICx1, WHEEL_TRUEx1 | $95.00 |  |
| 24 | m-1024 | downtown | OPEN | CHAIN_REPLACEx1 | $45.00 |  |
| 25 | m-1025 | northside | OPEN | BRAKE_ADJUSTx2, TIRE_REPLACEx2, CHAIN_REPLACEx1, TUNE_BASICx1 | $186.00 |  |
| 26 | m-1026 | lakeshore | OPEN | GEAR_ADJUSTx1 | $25.00 |  |
| 27 | m-1027 | downtown | OPEN | BRAKE_ADJUSTx1 | $18.00 |  |
| 28 | m-1028 | northside | OPEN | GEAR_ADJUSTx1 | $25.00 |  |
| 29 | m-1029 | lakeshore | OPEN | BRAKE_PADSx2, BRAKE_BLEEDx2 | $150.00 |  |
| 30 | m-1030 | downtown | OPEN | FLAT_FIXx1 | $15.00 |  |
| 31 | m-1031 | northside | OPEN | WHEEL_TRUEx2 | $60.00 |  |
| 32 | m-1032 | lakeshore | OPEN | TUNE_BASICx1 | $65.00 |  |
| 33 | m-1033 | downtown | NEEDS_INFO | — | — |  |
| 34 | m-1034 | northside | OPEN | CHAIN_REPLACEx1 | $45.00 |  |
| 35 | m-1035 | lakeshore | OPEN | TIRE_REPLACEx2 | $40.00 |  |
| 36 | m-1036 | downtown | OPEN | EBIKE_DIAGx1 | $60.00 | inspect |
| 37 | m-1037 | northside | OPEN | BRAKE_BLEEDx1 | $40.00 |  |
| 38 | m-1038 | lakeshore | NEEDS_REVIEW | — | — |  |
| 39 | m-1039 | downtown | OPEN | TUNE_FULLx1, FLAT_FIXx1 | $200.00 |  |
| 40 | m-1040 | northside | OPEN | TUNE_BASICx2 | $130.00 |  |
