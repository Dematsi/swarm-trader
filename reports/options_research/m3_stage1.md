# M3 Stage-1 Report (stock-level evaluation, development period)

- period: 2021-06-18..2025-12-31
- signals: 51565
- tickers: 12
- sessions with signals: 1135
- signals within one session of a split: 62
- ledger entries appended this run: 0

## Pass/fail (primary horizon: +60 min)

| setup         | direction   |    n |   mean_bps |     t |   positive_years |   break_even_bps |   cost_ratio | pass_n   | pass_t   | pass_years   | pass_cost   | passed   |
|:--------------|:------------|-----:|-----------:|------:|-----------------:|-----------------:|-------------:|:---------|:---------|:-------------|:------------|:---------|
| GAP_FILL      | long        | 1272 |       6.28 |  1.03 |                4 |             4.55 |         1.38 | True     | False    | True         | False       | False    |
| GAP_FILL      | short       | 1428 |      -6.59 | -1.33 |                1 |             4.52 |        -1.46 | True     | False    | False        | False       | False    |
| GAP_GO        | long        | 1715 |       1.93 |  0.49 |                4 |             4.54 |         0.42 | True     | False    | True         | False       | False    |
| GAP_GO        | short       | 1538 |       4.39 |  0.95 |                3 |             4.57 |         0.96 | True     | False    | False        | False       | False    |
| MEANREV       | long        |   51 |       8.21 |  0.54 |                3 |             4.49 |         1.83 | False    | False    | False        | True        | False    |
| MEANREV       | short       |   45 |     -46    | -1.37 |                2 |             4.82 |        -9.54 | False    | False    | False        | False       | False    |
| ORB15         | long        | 2163 |       0.15 |  0.04 |                3 |             4.53 |         0.03 | True     | False    | False        | False       | False    |
| ORB15         | short       | 2163 |      -2.18 | -0.75 |                1 |             4.53 |        -0.48 | True     | False    | False        | False       | False    |
| ORB30         | long        | 1700 |      -0.37 | -0.11 |                3 |             4.52 |        -0.08 | True     | False    | False        | False       | False    |
| ORB30         | short       | 1675 |      -0.52 | -0.16 |                2 |             4.54 |        -0.11 | True     | False    | False        | False       | False    |
| PDL_BREAK     | long        | 6201 |       3.19 |  1.6  |                5 |             4.53 |         0.7  | True     | False    | True         | False       | False    |
| PDL_BREAK     | short       | 5522 |      -0.73 | -0.28 |                2 |             4.55 |        -0.16 | True     | False    | False        | False       | False    |
| SQUEEZE       | long        | 3247 |       4.38 |  2.99 |                5 |             4.54 |         0.97 | True     | False    | True         | False       | False    |
| SQUEEZE       | short       | 3011 |       1.25 |  0.72 |                3 |             4.53 |         0.28 | True     | False    | False        | False       | False    |
| VWAP_PULLBACK | long        | 5177 |       2.47 |  1.41 |                4 |             4.53 |         0.55 | True     | False    | True         | False       | False    |
| VWAP_PULLBACK | short       | 4733 |       0.56 |  0.44 |                4 |             4.55 |         0.12 | True     | False    | True         | False       | False    |
| VWAP_RECLAIM  | long        | 4821 |       1.14 |  0.87 |                4 |             4.55 |         0.25 | True     | False    | True         | False       | False    |
| VWAP_RECLAIM  | short       | 5103 |      -1.75 | -1.09 |                2 |             4.54 |        -0.39 | True     | False    | False        | False       | False    |

Passing setup x direction pairs: 0 of 18

## Criteria (spec §8.3, pre-registered)

- Day-block bootstrap t >= 3.0 (10,000 resamples of trading days, seed 20260912)
- Mean +60 min return > 0 in >= 4 of the 5 calendar years (2021 H2 counts as a year)
- Mean +60 min return >= 1.5 x pooled break-even move (ATM NEAR option, round-trip half-spreads + fees, delta 0.5)
- >= 300 signals

## Horizons

| setup         | direction   |    n |   mean_ret_30 |   mean_ret_60 |   mean_ret_hard |   median_mfe_60 |   median_mae_60 |
|:--------------|:------------|-----:|--------------:|--------------:|----------------:|----------------:|----------------:|
| GAP_FILL      | long        | 1272 |          4.37 |          6.28 |            0.02 |           62.25 |          -59.18 |
| GAP_FILL      | short       | 1428 |         -8.84 |         -6.59 |           -0.47 |           54.31 |          -60.96 |
| GAP_GO        | long        | 1715 |          4.79 |          1.93 |            4.68 |           54.83 |          -53.41 |
| GAP_GO        | short       | 1538 |          4.74 |          4.39 |            8.97 |           63.35 |          -55.37 |
| MEANREV       | long        |   51 |         10.16 |          8.21 |          -17.84 |           37.24 |          -39.62 |
| MEANREV       | short       |   45 |        -27.25 |        -46    |          -61.74 |           36.69 |          -39.02 |
| ORB15         | long        | 2163 |          2.14 |          0.15 |            6.31 |           46.11 |          -48.99 |
| ORB15         | short       | 2163 |         -1.75 |         -2.18 |            0.74 |           48.86 |          -48.51 |
| ORB30         | long        | 1700 |         -1.79 |         -0.37 |            5.1  |           41.5  |          -47.35 |
| ORB30         | short       | 1675 |         -3.19 |         -0.52 |           -0.7  |           45.08 |          -45.22 |
| PDL_BREAK     | long        | 6201 |          2.55 |          3.19 |            4.94 |           39.26 |          -38.53 |
| PDL_BREAK     | short       | 5522 |         -1.84 |         -0.73 |            0.47 |           45.87 |          -44.25 |
| SQUEEZE       | long        | 3247 |          3.21 |          4.38 |            3.94 |           25.2  |          -22.4  |
| SQUEEZE       | short       | 3011 |          1.84 |          1.25 |           -1.29 |           27.07 |          -25.6  |
| VWAP_PULLBACK | long        | 5177 |          1.4  |          2.47 |            5.64 |           25.93 |          -26.3  |
| VWAP_PULLBACK | short       | 4733 |          0.26 |          0.56 |            1.55 |           27.65 |          -27.37 |
| VWAP_RECLAIM  | long        | 4821 |          0.24 |          1.14 |            0.94 |           28.84 |          -29.37 |
| VWAP_RECLAIM  | short       | 5103 |         -0.43 |         -1.75 |           -4.77 |           30.04 |          -28.96 |

## With and without event days

Event day = a Tier 1/2 macro release that day, or the ticker's earnings reaction day.

| setup         | direction   |   n_all |   mean_all |   t_all |   n_ex_event |   mean_ex_event |   t_ex_event |
|:--------------|:------------|--------:|-----------:|--------:|-------------:|----------------:|-------------:|
| GAP_FILL      | long        |    1272 |       6.28 |    1.04 |          667 |            9.09 |         1.07 |
| GAP_FILL      | short       |    1428 |      -6.59 |   -1.33 |          703 |           -9.81 |        -1.48 |
| GAP_GO        | long        |    1715 |       1.93 |    0.48 |          874 |            4.26 |         0.7  |
| GAP_GO        | short       |    1538 |       4.39 |    0.96 |          847 |            3.34 |         0.52 |
| MEANREV       | long        |      51 |       8.21 |    0.54 |           18 |           17.13 |         1.21 |
| MEANREV       | short       |      45 |     -46    |   -1.33 |           17 |            3.49 |         0.13 |
| ORB15         | long        |    2163 |       0.15 |    0.04 |         1117 |            1.17 |         0.21 |
| ORB15         | short       |    2163 |      -2.18 |   -0.74 |         1100 |           -2.31 |        -0.6  |
| ORB30         | long        |    1700 |      -0.37 |   -0.11 |          868 |            1.68 |         0.36 |
| ORB30         | short       |    1675 |      -0.52 |   -0.16 |          835 |           -0.08 |        -0.02 |
| PDL_BREAK     | long        |    6201 |       3.19 |    1.57 |         3142 |            4.72 |         1.91 |
| PDL_BREAK     | short       |    5522 |      -0.73 |   -0.27 |         2867 |            0.22 |         0.06 |
| SQUEEZE       | long        |    3247 |       4.38 |    2.95 |         1717 |            3.74 |         2.47 |
| SQUEEZE       | short       |    3011 |       1.25 |    0.72 |         1524 |            3.47 |         1.67 |
| VWAP_PULLBACK | long        |    5177 |       2.47 |    1.43 |         2645 |            0.63 |         0.34 |
| VWAP_PULLBACK | short       |    4733 |       0.56 |    0.45 |         2399 |            1.42 |         0.78 |
| VWAP_RECLAIM  | long        |    4821 |       1.14 |    0.89 |         2402 |            0.06 |         0.04 |
| VWAP_RECLAIM  | short       |    5103 |      -1.75 |   -1.1  |         2572 |            0.65 |         0.31 |

## Mean +60 min return by ticker (bps)

|                            |   AAPL |   AMD |   AMZN |   GOOGL |   IWM |   META |   MSFT |   NFLX |   NVDA |   QQQ |   SPY |   TSLA |
|:---------------------------|-------:|------:|-------:|--------:|------:|-------:|-------:|-------:|-------:|------:|------:|-------:|
| ('GAP_FILL', 'long')       |   -1.1 |  -5.5 |   23.5 |    -3.8 |  12   |    6.5 |    2.5 |    7.6 |    3   |  18.5 |  17   |   10.5 |
| ('GAP_FILL', 'short')      |   -5.1 | -10.2 |   -4   |    -1.8 |   0.5 |  -12.4 |   -0.8 |   -8.2 |  -14.1 |   0.8 |  -3.6 |   -5.5 |
| ('GAP_GO', 'long')         |    3   |  11.9 |   -1.4 |     2.4 |  -0.2 |  -15.2 |   -3.8 |   -2.3 |   14.4 |   3.5 |   7.7 |   -3.8 |
| ('GAP_GO', 'short')        |   -3.1 |  10.9 |    1   |     4.2 |  -5.4 |   -9.3 |   10.3 |    8.3 |    6.8 |   5   |  10.2 |    8.7 |
| ('MEANREV', 'long')        |   27   |  35.1 |   20.8 |    -1.8 |  14.5 |   25.4 |   25.1 | -114.7 |   37.9 | -18   |  -5.6 |   -4.5 |
| ('MEANREV', 'short')       |   97.9 |  19.2 | -175.2 |    17.2 |  15.7 | -261.5 | -343.6 |  -35.6 | -122.1 |  11.2 |  -7.8 |  -19.3 |
| ('ORB15', 'long')          |   -3   |  14.4 |   -3.6 |    -6.8 |  -1.9 |  -10.4 |   -3.5 |    0.7 |   -0.7 |   1   |   2.1 |   13.4 |
| ('ORB15', 'short')         |    0.4 |  -7.6 |   -1.4 |    -5.7 |   1.4 |  -13.9 |   -0.9 |    3.4 |    1.1 |   2.9 |   5.7 |  -14.8 |
| ('ORB30', 'long')          |    2.6 |  16.2 |   -2.3 |    -6.9 |   1.9 |   -1.9 |  -10.6 |  -10.8 |   -8   |  -5.7 |  -2.5 |   24.3 |
| ('ORB30', 'short')         |    3.8 |  10.2 |    2.3 |    -0.9 |  -2.3 |   -7.9 |   -5.8 |   -3.5 |  -17.2 |   2.1 |   2.7 |   13.9 |
| ('PDL_BREAK', 'long')      |    4.1 |   9.2 |    2.5 |    -1.5 |   3   |   -5.4 |    3.1 |    3.3 |    7.3 |   1.5 |   3.2 |    8.9 |
| ('PDL_BREAK', 'short')     |    1.1 |  -0.8 |    2.4 |     2.2 |   0.4 |   -3.4 |    0.3 |    2   |   -3.2 |  -2.1 |  -2.7 |   -4.7 |
| ('SQUEEZE', 'long')        |    4.2 |   4.8 |    5.4 |     5.7 |  -3.6 |    3   |    7.3 |    4   |   10.3 |   3.1 |   5.1 |    1   |
| ('SQUEEZE', 'short')       |    2.8 |   7.7 |    2.7 |     7.6 |   1.8 |    0.9 |    2.6 |   -0.7 |   -8.7 |  -2.4 |  -0.4 |    1.9 |
| ('VWAP_PULLBACK', 'long')  |    1.1 |  -0.9 |   -2.8 |     6.6 |   1.2 |    3.1 |    1.7 |    8.4 |    4.5 |   4.2 |   1.6 |    1.7 |
| ('VWAP_PULLBACK', 'short') |   -0.5 |   3   |    0.4 |     4.2 |   4.4 |   -3.5 |    0.1 |   -0.1 |    2.4 |  -2.4 |  -1   |    2.4 |
| ('VWAP_RECLAIM', 'long')   |   -0.5 |   0.4 |    1.4 |    -1.1 |   2.6 |    3.7 |    1.1 |    1.4 |    4.5 |   2.6 |   0.6 |   -2.9 |
| ('VWAP_RECLAIM', 'short')  |   -2.1 |  -1.6 |   -5.7 |    -0.2 |   0.7 |   -2.9 |   -2.8 |    1   |   -8.1 |   0.7 |   0.3 |   -0.3 |

## Break-even move by ticker (bps, median)

| symbol   |   break_even_bps |
|:---------|-----------------:|
| AAPL     |             2.66 |
| AMD      |            23.4  |
| AMZN     |             4.04 |
| GOOGL    |             6.03 |
| IWM      |             1.47 |
| META     |             8.82 |
| MSFT     |            10.17 |
| NFLX     |             5.04 |
| NVDA     |             1.96 |
| QQQ      |             0.91 |
| SPY      |             0.31 |
| TSLA     |             5.67 |

## Multiple-testing ledger

- Stage-1 configurations recorded: 18
- Expected false passes under the null (one-sided p at t = 3): 0.024
