# M2 Cost Model Report

## Calibration

- rv_cal: 0.003987112476290289
- sessions: 15
- window: 2026-08-21..2026-09-11
- cells: 1953

## Cells by level (n >= 30 usable)

|   level |   cells |   usable |
|--------:|--------:|---------:|
|       1 |      12 |       12 |
|       2 |      48 |       48 |
|       3 |     192 |      192 |
|       4 |     440 |      401 |
|       5 |    1261 |     1039 |

## ATM full spread as % of median mid (level 3: underlying x DTE x moneyness)

| underlying   |    0 |   1-2 |   3-7 |   8+ |
|:-------------|-----:|------:|------:|-----:|
| AAPL         | 3.23 |  2.01 |  3.9  | 4.39 |
| AMD          | 7.76 |  5.19 |  4.94 | 7.96 |
| AMZN         | 5.95 |  2.36 |  4.18 | 5.05 |
| GOOGL        | 7.25 |  4.45 |  7.04 | 6.37 |
| IWM          | 2.53 |  1.44 |  2.3  | 2.1  |
| META         | 5.35 |  3.83 |  4.07 | 5.51 |
| MSFT         | 7.87 |  6.8  |  7.14 | 7.88 |
| NFLX         | 8.16 |  4.14 |  2.12 | 2.41 |
| NVDA         | 2.65 |  0.89 |  1.48 | 2.84 |
| QQQ          | 0.85 |  0.84 |  0.91 | 0.96 |
| SPY          | 1.12 |  0.77 |  0.76 | 0.82 |
| TSLA         | 1.98 |  2.15 |  1.47 | 1.5  |

Stress multipliers applied in stage 2: h x 1.5 and h x 2.0 (spec §5.6).
