"""Synthetic statement exports (fictional accounts and balances) in the real column layouts."""

FIDELITY_POSITIONS_CSV = (
    "Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value,Today's Gain/Loss Dollar,Total Gain/Loss Dollar,Cost Basis Total,Average Cost Basis,Type\n"
    'TEST0001,Fidelity Individual Brokerage,VGT,VANGUARD WORLD FD INFORMATION TECHNOLOGY ETF,75,$610.25,$2.10,"$45,768.75",$157.50,"$9,768.75","$36,000.00",$480.00,Cash\n'
    'TEST0001,Fidelity Individual Brokerage,NVDA,NVIDIA CORP COM,150,$135.40,-$1.20,"$20,310.00",-$180.00,"$8,310.00","$12,000.00",$80.00,Cash\n'
    'TEST0001,Fidelity Individual Brokerage,SPAXX**,HELD IN MONEY MARKET,,,,"$25,000.00",,,,,Cash\n'
    "\n"
    '"The data and information in this spreadsheet is provided to you solely for your use."\n'
)

NATIONWIDE_BALANCES_CSV = (
    "Fund Name,Units,Unit Value,Balance\n"
    'Vanguard Target Retirement 2045 Trust,"1,200.5",$41.20,"$49,460.60"\n'
    'Nationwide S&P 500 Index Fund,310.2,$55.10,"$17,092.02"\n'
    'Nationwide Fixed Fund,"2,000.0",$1.00,"$2,000.00"\n'
)
