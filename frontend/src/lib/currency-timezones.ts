/**
 * Currency → timezone derivation for the settings form.
 *
 * ICU knows a region's timezones (`Intl.Locale#getTimeZones`) but nothing ties
 * a currency to its regions, so that one hop is a static table: each active
 * ISO 4217 currency and the ISO 3166 regions that use it. Timezones are then
 * looked up at runtime, so the zone data itself never goes stale.
 *
 * The table doubles as the currency dropdown's source: it holds only real,
 * circulating currencies, unlike `Intl.supportedValuesOf("currency")` which
 * includes funds, metals and retired codes.
 */
const CURRENCY_REGIONS: Record<string, string[]> = {
  AED: ["AE"],
  AFN: ["AF"],
  ALL: ["AL"],
  AMD: ["AM"],
  ANG: ["CW", "SX"],
  AOA: ["AO"],
  ARS: ["AR"],
  AUD: ["AU", "CX", "CC", "KI", "NR", "NF", "TV"],
  AWG: ["AW"],
  AZN: ["AZ"],
  BAM: ["BA"],
  BBD: ["BB"],
  BDT: ["BD"],
  BGN: ["BG"],
  BHD: ["BH"],
  BIF: ["BI"],
  BMD: ["BM"],
  BND: ["BN"],
  BOB: ["BO"],
  BRL: ["BR"],
  BSD: ["BS"],
  BTN: ["BT"],
  BWP: ["BW"],
  BYN: ["BY"],
  BZD: ["BZ"],
  CAD: ["CA"],
  CDF: ["CD"],
  CHF: ["CH", "LI"],
  CLP: ["CL"],
  CNY: ["CN"],
  COP: ["CO"],
  CRC: ["CR"],
  CUP: ["CU"],
  CVE: ["CV"],
  CZK: ["CZ"],
  DJF: ["DJ"],
  DKK: ["DK", "FO", "GL"],
  DOP: ["DO"],
  DZD: ["DZ"],
  EGP: ["EG"],
  ERN: ["ER"],
  ETB: ["ET"],
  EUR: [
    "AD", "AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE",
    "IT", "LT", "LU", "LV", "MC", "ME", "MT", "NL", "PT", "SI", "SK", "SM",
    "VA", "XK",
  ],
  FJD: ["FJ"],
  FKP: ["FK"],
  GBP: ["GB", "GG", "IM", "JE"],
  GEL: ["GE"],
  GHS: ["GH"],
  GIP: ["GI"],
  GMD: ["GM"],
  GNF: ["GN"],
  GTQ: ["GT"],
  GYD: ["GY"],
  HKD: ["HK"],
  HNL: ["HN"],
  HTG: ["HT"],
  HUF: ["HU"],
  IDR: ["ID"],
  ILS: ["IL"],
  INR: ["IN"],
  IQD: ["IQ"],
  IRR: ["IR"],
  ISK: ["IS"],
  JMD: ["JM"],
  JOD: ["JO"],
  JPY: ["JP"],
  KES: ["KE"],
  KGS: ["KG"],
  KHR: ["KH"],
  KMF: ["KM"],
  KPW: ["KP"],
  KRW: ["KR"],
  KWD: ["KW"],
  KYD: ["KY"],
  KZT: ["KZ"],
  LAK: ["LA"],
  LBP: ["LB"],
  LKR: ["LK"],
  LRD: ["LR"],
  LSL: ["LS"],
  LYD: ["LY"],
  MAD: ["MA", "EH"],
  MDL: ["MD"],
  MGA: ["MG"],
  MKD: ["MK"],
  MMK: ["MM"],
  MNT: ["MN"],
  MOP: ["MO"],
  MRU: ["MR"],
  MUR: ["MU"],
  MVR: ["MV"],
  MWK: ["MW"],
  MXN: ["MX"],
  MYR: ["MY"],
  MZN: ["MZ"],
  NAD: ["NA"],
  NGN: ["NG"],
  NIO: ["NI"],
  NOK: ["NO", "SJ"],
  NPR: ["NP"],
  NZD: ["NZ", "CK", "NU", "PN", "TK"],
  OMR: ["OM"],
  PAB: ["PA"],
  PEN: ["PE"],
  PGK: ["PG"],
  PHP: ["PH"],
  PKR: ["PK"],
  PLN: ["PL"],
  PYG: ["PY"],
  QAR: ["QA"],
  RON: ["RO"],
  RSD: ["RS"],
  RUB: ["RU"],
  RWF: ["RW"],
  SAR: ["SA"],
  SBD: ["SB"],
  SCR: ["SC"],
  SDG: ["SD"],
  SEK: ["SE"],
  SGD: ["SG"],
  SHP: ["SH"],
  SLE: ["SL"],
  SOS: ["SO"],
  SRD: ["SR"],
  SSP: ["SS"],
  STN: ["ST"],
  SYP: ["SY"],
  SZL: ["SZ"],
  THB: ["TH"],
  TJS: ["TJ"],
  TMT: ["TM"],
  TND: ["TN"],
  TOP: ["TO"],
  TRY: ["TR"],
  TTD: ["TT"],
  TWD: ["TW"],
  TZS: ["TZ"],
  UAH: ["UA"],
  UGX: ["UG"],
  USD: [
    "US", "AS", "BQ", "EC", "FM", "GU", "MH", "MP", "PR", "PW", "SV", "TC",
    "TL", "VG", "VI",
  ],
  UYU: ["UY"],
  UZS: ["UZ"],
  VES: ["VE"],
  VND: ["VN"],
  VUV: ["VU"],
  WST: ["WS"],
  XAF: ["CM", "CF", "CG", "GA", "GQ", "TD"],
  XCD: ["AG", "AI", "DM", "GD", "KN", "LC", "MS", "VC"],
  XOF: ["BJ", "BF", "CI", "GW", "ML", "NE", "SN", "TG"],
  XPF: ["PF", "NC", "WF"],
  YER: ["YE"],
  ZAR: ["ZA"],
  ZMW: ["ZM"],
  ZWG: ["ZW"],
};

export const CURRENCY_CODES: string[] = Object.keys(CURRENCY_REGIONS).sort();

function regionTimeZones(region: string): string[] {
  try {
    const locale = new Intl.Locale("und", { region });
    // Spec renamed the `timeZones` accessor to `getTimeZones()`; runtimes ship
    // one or the other depending on ICU vintage.
    const candidate = locale as {
      getTimeZones?: () => string[];
      timeZones?: string[];
    };
    const zones =
      typeof candidate.getTimeZones === "function"
        ? candidate.getTimeZones()
        : candidate.timeZones;
    return Array.isArray(zones) ? zones : [];
  } catch {
    return [];
  }
}

/**
 * Timezones used where `currency` circulates, alphabetical. Empty when the
 * currency is unknown or the runtime cannot resolve regions — the caller
 * should fall back to the full timezone list rather than an empty select.
 */
export function timezonesForCurrency(currency: string): string[] {
  const regions = CURRENCY_REGIONS[currency];
  if (!regions) return [];
  const zones = new Set<string>();
  for (const region of regions) {
    for (const zone of regionTimeZones(region)) zones.add(zone);
  }
  return [...zones].sort();
}
