"""Metro areas for filtering and the map. EX-102 has no coordinates, only
city, county and state; metros are defined by county (roughly the Census
CBSAs) and plotted at their center. Other loans plot at their state's
center."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Metro:
    id: str
    name: str
    lat: float
    lon: float
    counties: dict[str, tuple[str, ...]] = field(default_factory=dict)  # state -> counties (lowercase, no "county")
    cities: dict[str, tuple[str, ...]] = field(default_factory=dict)  # fallback when county is blank

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "lat": self.lat, "lon": self.lon}


METROS = [
    Metro("nyc", "New York", 40.7128, -74.0060,
          {"NY": ("new york", "kings", "queens", "bronx", "richmond", "nassau", "suffolk", "westchester", "rockland", "putnam"),
           "NJ": ("bergen", "hudson", "essex", "passaic", "union", "middlesex", "monmouth", "morris", "somerset", "ocean", "hunterdon", "sussex")},
          {"NY": ("new york", "manhattan", "brooklyn", "bronx", "queens", "staten island", "long island city", "flushing", "jamaica", "astoria")}),
    Metro("la", "Los Angeles", 34.0522, -118.2437, {"CA": ("los angeles", "orange")}, {"CA": ("los angeles",)}),
    Metro("chicago", "Chicago", 41.8781, -87.6298,
          {"IL": ("cook", "dupage", "lake", "will", "kane", "mchenry"), "IN": ("lake", "porter")}, {"IL": ("chicago",)}),
    Metro("dc", "Washington DC", 38.9072, -77.0369,
          {"DC": ("district of columbia",),
           "VA": ("arlington", "fairfax", "alexandria", "loudoun", "prince william", "alexandria city", "fairfax city"),
           "MD": ("montgomery", "prince george's", "prince georges", "frederick", "charles")}, {"DC": ("washington",)}),
    Metro("sf", "San Francisco Bay Area", 37.7749, -122.4194,
          {"CA": ("san francisco", "alameda", "contra costa", "san mateo", "marin", "santa clara")},
          {"CA": ("san francisco", "oakland", "san jose")}),
    Metro("boston", "Boston", 42.3601, -71.0589, {"MA": ("suffolk", "middlesex", "norfolk", "essex", "plymouth")}, {"MA": ("boston", "cambridge")}),
    Metro("dallas", "Dallas-Fort Worth", 32.7767, -96.7970,
          {"TX": ("dallas", "tarrant", "collin", "denton", "rockwall", "kaufman", "ellis", "johnson", "parker")},
          {"TX": ("dallas", "fort worth", "plano", "irving", "arlington")}),
    Metro("houston", "Houston", 29.7604, -95.3698, {"TX": ("harris", "fort bend", "montgomery", "brazoria", "galveston")}, {"TX": ("houston",)}),
    Metro("miami", "Miami", 25.7617, -80.1918, {"FL": ("miami-dade", "miami dade", "dade", "broward", "palm beach")}, {"FL": ("miami", "fort lauderdale")}),
    Metro("atlanta", "Atlanta", 33.7490, -84.3880,
          {"GA": ("fulton", "dekalb", "cobb", "gwinnett", "clayton", "cherokee", "forsyth", "henry")}, {"GA": ("atlanta",)}),
    Metro("phoenix", "Phoenix", 33.4484, -112.0740, {"AZ": ("maricopa", "pinal")}, {"AZ": ("phoenix", "scottsdale", "tempe")}),
    Metro("seattle", "Seattle", 47.6062, -122.3321, {"WA": ("king", "snohomish", "pierce")}, {"WA": ("seattle", "bellevue")}),
    Metro("philadelphia", "Philadelphia", 39.9526, -75.1652,
          {"PA": ("philadelphia", "montgomery", "bucks", "delaware", "chester"), "NJ": ("camden", "burlington", "gloucester")},
          {"PA": ("philadelphia",)}),
    Metro("denver", "Denver", 39.7392, -104.9903, {"CO": ("denver", "arapahoe", "jefferson", "adams", "douglas", "broomfield")}, {"CO": ("denver",)}),
    Metro("austin", "Austin", 30.2672, -97.7431, {"TX": ("travis", "williamson", "hays")}, {"TX": ("austin",)}),
    Metro("san_diego", "San Diego", 32.7157, -117.1611, {"CA": ("san diego",)}, {"CA": ("san diego",)}),
    Metro("inland_empire", "Inland Empire", 34.0555, -117.1825, {"CA": ("riverside", "san bernardino")}),
    Metro("las_vegas", "Las Vegas", 36.1699, -115.1398, {"NV": ("clark",)}, {"NV": ("las vegas",)}),
    Metro("minneapolis", "Minneapolis", 44.9778, -93.2650,
          {"MN": ("hennepin", "ramsey", "dakota", "anoka", "washington")}, {"MN": ("minneapolis", "saint paul", "st. paul")}),
    Metro("detroit", "Detroit", 42.3314, -83.0458, {"MI": ("wayne", "oakland", "macomb")}, {"MI": ("detroit",)}),
    Metro("orlando", "Orlando", 28.5383, -81.3792, {"FL": ("orange", "osceola", "seminole")}, {"FL": ("orlando",)}),
    Metro("tampa", "Tampa", 27.9506, -82.4572, {"FL": ("hillsborough", "pinellas", "pasco")}, {"FL": ("tampa", "st. petersburg")}),
    Metro("honolulu", "Honolulu", 21.3069, -157.8583, {"HI": ("honolulu",)}, {"HI": ("honolulu",)}),
]
BY_ID = {m.id: m for m in METROS}


def metro_for(state: str, county: str, city: str) -> str:
    st = state.strip().upper()
    c = _norm_county(county)
    ct = city.strip().lower()
    for m in METROS:
        if c:
            if c in m.counties.get(st, ()):
                return m.id
            continue  # county known and not in this metro
        if ct in m.cities.get(st, ()):
            return m.id
    return ""


def _norm_county(s: str) -> str:
    s = s.strip().lower()
    for suffix in (" county", " parish"):
        s = s.removesuffix(suffix)
    return s


def point(metro: str, state: str) -> tuple[float, float] | None:
    """Where a location is drawn: its metro's center, else its state's."""
    if metro in BY_ID:
        m = BY_ID[metro]
        return m.lat, m.lon
    return STATE_CENTERS.get(state.upper())


STATE_CENTERS = {
    "AL": (32.8, -86.8), "AK": (61.4, -152.3), "AZ": (34.2, -111.6), "AR": (34.9, -92.4), "CA": (37.2, -119.4),
    "CO": (39.0, -105.5), "CT": (41.6, -72.7), "DE": (39.0, -75.5), "DC": (38.9, -77.0), "FL": (28.6, -82.4),
    "GA": (32.7, -83.4), "HI": (20.8, -156.3), "ID": (44.4, -114.6), "IL": (40.0, -89.2), "IN": (39.9, -86.3),
    "IA": (42.1, -93.5), "KS": (38.5, -98.4), "KY": (37.5, -85.3), "LA": (31.1, -92.0), "ME": (45.4, -69.2),
    "MD": (39.0, -76.8), "MA": (42.3, -71.8), "MI": (44.3, -85.4), "MN": (46.3, -94.3), "MS": (32.7, -89.7),
    "MO": (38.4, -92.5), "MT": (47.0, -109.6), "NE": (41.5, -99.8), "NV": (39.3, -116.6), "NH": (43.7, -71.6),
    "NJ": (40.2, -74.7), "NM": (34.4, -106.1), "NY": (42.9, -75.5), "NC": (35.6, -79.4), "ND": (47.5, -100.5),
    "OH": (40.3, -82.8), "OK": (35.6, -97.5), "OR": (43.9, -120.6), "PA": (40.9, -77.8), "RI": (41.7, -71.5),
    "SC": (33.9, -80.9), "SD": (44.4, -100.2), "TN": (35.9, -86.4), "TX": (31.5, -99.3), "UT": (39.3, -111.7),
    "VT": (44.1, -72.7), "VA": (37.5, -78.9), "WA": (47.4, -120.5), "WV": (38.6, -80.6), "WI": (44.6, -89.9),
    "WY": (43.0, -107.6), "PR": (18.2, -66.5),
}
