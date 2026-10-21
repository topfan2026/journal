import type { SymbolInfo } from '../lib/types';

// symbol | name | sector | market cap ($B) | EPS growth % | reference price | annualized vol
// Fundamentals are illustrative values for the simulator, not live data.
const TABLE = `
AAPL|Apple Inc.|Technology|3450|9.8|228|0.24
MSFT|Microsoft Corp.|Technology|3200|17.5|425|0.22
NVDA|NVIDIA Corp.|Technology|3350|112|138|0.5
AMZN|Amazon.com Inc.|Consumer Disc.|1980|64.2|188|0.3
GOOGL|Alphabet Inc.|Communication|2050|31|166|0.28
META|Meta Platforms Inc.|Communication|1460|58.4|575|0.36
TSLA|Tesla Inc.|Consumer Disc.|700|-22.5|220|0.6
AVGO|Broadcom Inc.|Technology|810|24.1|172|0.42
BRK.B|Berkshire Hathaway|Financials|990|15.2|460|0.16
JPM|JPMorgan Chase & Co.|Financials|620|12.3|222|0.21
V|Visa Inc.|Financials|560|11|285|0.18
MA|Mastercard Inc.|Financials|470|13.4|510|0.19
LLY|Eli Lilly & Co.|Healthcare|830|85|905|0.32
UNH|UnitedHealth Group|Healthcare|540|-4.1|590|0.25
JNJ|Johnson & Johnson|Healthcare|390|3.2|162|0.15
ABBV|AbbVie Inc.|Healthcare|340|-8.4|195|0.22
MRK|Merck & Co.|Healthcare|260|45.1|102|0.2
PFE|Pfizer Inc.|Healthcare|165|-42|29|0.24
TMO|Thermo Fisher Scientific|Healthcare|225|2.1|590|0.22
ABT|Abbott Laboratories|Healthcare|200|4.8|116|0.19
ISRG|Intuitive Surgical|Healthcare|180|23.7|510|0.3
XOM|Exxon Mobil Corp.|Energy|520|-9.5|119|0.23
CVX|Chevron Corp.|Energy|280|-14.2|152|0.24
COP|ConocoPhillips|Energy|135|-11|108|0.28
SLB|Schlumberger Ltd.|Energy|60|9.1|42|0.32
COST|Costco Wholesale|Consumer Staples|395|13.7|890|0.19
WMT|Walmart Inc.|Consumer Staples|650|11.6|81|0.17
PG|Procter & Gamble|Consumer Staples|400|6.1|170|0.15
KO|Coca-Cola Co.|Consumer Staples|300|6.8|70|0.15
PEP|PepsiCo Inc.|Consumer Staples|230|5.2|168|0.16
MCD|McDonald's Corp.|Consumer Disc.|220|2.9|305|0.17
NKE|Nike Inc.|Consumer Disc.|120|-12.4|80|0.3
SBUX|Starbucks Corp.|Consumer Disc.|110|-9.8|97|0.28
HD|Home Depot Inc.|Consumer Disc.|400|-2.4|405|0.2
LOW|Lowe's Companies|Consumer Disc.|150|-5.1|268|0.23
DIS|Walt Disney Co.|Communication|200|28.5|110|0.25
NFLX|Netflix Inc.|Communication|330|41|765|0.35
CMCSA|Comcast Corp.|Communication|160|9.4|42|0.22
T|AT&T Inc.|Communication|160|-3.2|22|0.18
VZ|Verizon Communications|Communication|175|-1.5|42|0.17
AMD|Advanced Micro Devices|Technology|250|19.2|156|0.48
INTC|Intel Corp.|Technology|95|-85|22|0.45
QCOM|Qualcomm Inc.|Technology|185|32|168|0.33
TXN|Texas Instruments|Technology|180|-18|200|0.25
MU|Micron Technology|Technology|115|180|104|0.5
AMAT|Applied Materials|Technology|160|12.8|195|0.38
LRCX|Lam Research|Technology|95|14.1|74|0.42
ADI|Analog Devices|Technology|110|-20|225|0.27
ORCL|Oracle Corp.|Technology|480|15.4|172|0.32
CRM|Salesforce Inc.|Technology|280|27.3|292|0.3
ADBE|Adobe Inc.|Technology|225|14.6|505|0.31
NOW|ServiceNow Inc.|Technology|190|21.4|930|0.33
INTU|Intuit Inc.|Technology|180|16.2|640|0.28
IBM|IBM Corp.|Technology|210|9|230|0.2
CSCO|Cisco Systems|Technology|230|-6.2|57|0.19
ANET|Arista Networks|Technology|120|34|380|0.4
PANW|Palo Alto Networks|Technology|125|22|370|0.33
CRWD|CrowdStrike Holdings|Technology|85|48|345|0.45
SNOW|Snowflake Inc.|Technology|40|-15|120|0.5
PLTR|Palantir Technologies|Technology|95|120|42|0.65
SMCI|Super Micro Computer|Technology|28|88|48|0.9
SHOP|Shopify Inc.|Technology|105|62|80|0.5
UBER|Uber Technologies|Industrials|160|150|78|0.38
ABNB|Airbnb Inc.|Consumer Disc.|85|-12|135|0.38
PYPL|PayPal Holdings|Financials|80|18|78|0.33
SQ|Block Inc.|Financials|42|95|70|0.45
COIN|Coinbase Global|Financials|60|210|240|0.75
GS|Goldman Sachs Group|Financials|165|44|525|0.26
MS|Morgan Stanley|Financials|200|28|128|0.25
BAC|Bank of America|Financials|320|-2.5|42|0.24
WFC|Wells Fargo & Co.|Financials|210|6.5|63|0.26
C|Citigroup Inc.|Financials|120|8.8|64|0.28
SCHW|Charles Schwab|Financials|125|-6|68|0.3
BLK|BlackRock Inc.|Financials|145|12|970|0.22
AXP|American Express|Financials|190|24|270|0.24
CAT|Caterpillar Inc.|Industrials|190|8.9|395|0.27
DE|Deere & Co.|Industrials|110|-18|400|0.25
BA|Boeing Co.|Industrials|95|-140|155|0.4
GE|GE Aerospace|Industrials|200|65|185|0.32
HON|Honeywell International|Industrials|135|5.4|210|0.19
UPS|United Parcel Service|Industrials|110|-22|130|0.24
RTX|RTX Corp.|Industrials|160|18|123|0.22
LMT|Lockheed Martin|Industrials|140|2.5|585|0.18
UNP|Union Pacific|Industrials|150|6.7|245|0.2
NEE|NextEra Energy|Utilities|160|9.1|80|0.22
DUK|Duke Energy|Utilities|88|8.2|115|0.16
SO|Southern Co.|Utilities|98|11.5|90|0.16
LIN|Linde plc|Materials|225|9.4|475|0.18
FCX|Freeport-McMoRan|Materials|68|27|48|0.38
NEM|Newmont Corp.|Materials|65|60|56|0.36
AMT|American Tower|Real Estate|105|-4|225|0.24
PLD|Prologis Inc.|Real Estate|115|11|125|0.26
EQIX|Equinix Inc.|Real Estate|82|14|870|0.24
ROIV|Roivant Sciences|Healthcare|8|-35|11.8|0.5
QGEN|Qiagen N.V.|Healthcare|10|-8|44|0.25
CRWV|CoreWeave Inc.|Technology|60|-40|120|0.95
MEDP|Medpace Holdings|Healthcare|11|29|350|0.38
TDY|Teledyne Technologies|Industrials|22|5|470|0.22
ELS|Equity LifeStyle Properties|Real Estate|13|6|68|0.2
SPY|SPDR S&P 500 ETF|ETF|560|10|580|0.14
QQQ|Invesco QQQ Trust|ETF|300|14|495|0.19
IWM|iShares Russell 2000 ETF|ETF|70|8|222|0.2
DIA|SPDR Dow Jones ETF|ETF|35|9|425|0.13
`;

export const UNIVERSE: SymbolInfo[] = TABLE.trim().split('\n').map((row) => {
  const [symbol, name, sector, cap, eps, price, vol] = row.split('|');
  return { symbol, name, sector, marketCapB: +cap, epsGrowth: +eps, basePrice: +price, vol: +vol };
});

const bySector = (...sectors: string[]) => UNIVERSE.filter((u) => sectors.includes(u.sector)).map((u) => u.symbol);
const NON_ETF = UNIVERSE.filter((u) => u.sector !== 'ETF');

export const WATCHLISTS: Record<string, string[]> = {
  'High Cap': [...NON_ETF].sort((a, b) => b.marketCapB - a.marketCapB).map((u) => u.symbol),
  'Mega Caps': NON_ETF.filter((u) => u.marketCapB >= 700).map((u) => u.symbol),
  'NASDAQ 100': ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AVGO', 'COST', 'NFLX', 'AMD', 'PEP', 'ADBE', 'CSCO', 'QCOM', 'INTU', 'TXN', 'AMAT', 'ISRG', 'MU', 'LRCX', 'ADI', 'PANW', 'CRWD', 'SBUX', 'PYPL', 'CMCSA', 'HON', 'ABNB', 'PLTR', 'SMCI'],
  'Technology': bySector('Technology'),
  'Financials': bySector('Financials'),
  'Healthcare': bySector('Healthcare'),
  'Energy & Materials': bySector('Energy', 'Materials'),
  'Consumer': bySector('Consumer Disc.', 'Consumer Staples'),
  'Industrials & Utilities': bySector('Industrials', 'Utilities', 'Real Estate'),
  'ETFs': bySector('ETF'),
};

export const infoFor = (symbol: string): SymbolInfo =>
  UNIVERSE.find((s) => s.symbol === symbol) ?? {
    symbol, name: symbol, sector: '—', marketCapB: 0, epsGrowth: 0, basePrice: 100, vol: 0.3,
  };
