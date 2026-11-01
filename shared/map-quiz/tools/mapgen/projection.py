"""Map projections: callables (lon, lat) in degrees -> (easting, northing) in
metres, y north. Any such callable works with mapgen.Window and
mapgen.MapBuilder; these cover a continent (LAEA), a city (TM) and data
that comes already projected (Identity: e.g. EPSG:31256 coordinates).

Each projection can carry a reference point from the defining source
(EPSG); self_test() compares against it, so a typo in a constant fails the
build instead of drawing a slightly wrong map."""
import math

# (semi-major axis a in metres, inverse flattening 1/f)
GRS80 = (6378137.0, 298.257222101)
WGS84 = (6378137.0, 298.257223563)
BESSEL_1841 = (6377397.155, 299.1528128)
AIRY_1830 = (6377563.396, 299.3249646)


class Projection:
    reference = None  # (lon, lat, easting, northing)

    def self_test(self, tol=0.01):
        """Raises ValueError if the reference point doesn't come out within tol metres."""
        if not self.reference:
            return
        lon, lat, e0, n0 = self.reference
        e, n = self(lon, lat)
        if abs(e - e0) > tol or abs(n - n0) > tol:
            raise ValueError(f"{self!r}: projection self-test failed: {e:.2f} {n:.2f}, expected {e0} {n0}")


class Identity(Projection):
    """For input that is already projected (easting, northing in metres, y
    north): passes coordinates through; Window does the scaling and y-flip."""

    def __repr__(self):
        return "identity"

    def __call__(self, x, y):
        return x, y


class LambertAzimuthalEqualArea(Projection):
    """Snyder (1987) ellipsoidal LAEA, oblique aspect."""

    def __init__(self, lat0, lon0, fe=0.0, fn=0.0, ellipsoid=GRS80, reference=None, name="LAEA"):
        a, inv_f = ellipsoid
        f = 1 / inv_f
        self.a = a
        self.e2 = f * (2 - f)
        self.e = math.sqrt(self.e2)
        self.lat0, self.lon0 = math.radians(lat0), math.radians(lon0)
        self.fe, self.fn = fe, fn
        self.qp = self._q(math.pi / 2)
        self.rq = a * math.sqrt(self.qp / 2)
        self.b1 = math.asin(self._q(self.lat0) / self.qp)
        m1 = math.cos(self.lat0) / math.sqrt(1 - self.e2 * math.sin(self.lat0) ** 2)
        self.d = a * m1 / (self.rq * math.cos(self.b1))
        self.reference = reference
        self.name = name

    def __repr__(self):
        return self.name

    def _q(self, phi):
        e2, e = self.e2, self.e
        s = math.sin(phi)
        return (1 - e2) * (s / (1 - e2 * s * s) - (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))

    def __call__(self, lon, lat):
        lam, phi = math.radians(lon), math.radians(lat)
        beta = math.asin(self._q(phi) / self.qp)
        dl = lam - self.lon0
        b1, d = self.b1, self.d
        b = self.rq * math.sqrt(2 / (1 + math.sin(b1) * math.sin(beta) + math.cos(b1) * math.cos(beta) * math.cos(dl)))
        x = b * d * math.cos(beta) * math.sin(dl)
        y = (b / d) * (math.cos(b1) * math.sin(beta) - math.sin(b1) * math.cos(beta) * math.cos(dl))
        return self.fe + x, self.fn + y


def epsg3035():
    """ETRS89-extended / LAEA Europe: centre 52°N 10°E, GRS80; EPSG's reference point."""
    return LambertAzimuthalEqualArea(52, 10, 4321000.0, 3210000.0, GRS80,
                                     reference=(5, 50, 3962799.45, 2999718.85), name="EPSG:3035")


class TransverseMercator(Projection):
    """Ellipsoidal transverse Mercator (Gauss-Krüger), the series of EPSG
    Guidance Note 7-2 (Snyder's USGS formulas): accurate to well below a
    metre within a few degrees of the central meridian — plenty for a city
    or a country."""

    def __init__(self, lon0, lat0=0.0, k0=1.0, fe=0.0, fn=0.0, ellipsoid=GRS80, reference=None, name="TM"):
        a, inv_f = ellipsoid
        f = 1 / inv_f
        self.a, self.k0, self.fe, self.fn = a, k0, fe, fn
        self.e2 = f * (2 - f)
        self.ep2 = self.e2 / (1 - self.e2)
        self.lon0, self.lat0 = math.radians(lon0), math.radians(lat0)
        self.m0 = self._m(self.lat0)
        self.reference = reference
        self.name = name

    def __repr__(self):
        return self.name

    def _m(self, phi):
        e2 = self.e2
        e4, e6 = e2 * e2, e2 * e2 * e2
        return self.a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                         - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                         + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                         - (35 * e6 / 3072) * math.sin(6 * phi))

    def __call__(self, lon, lat):
        phi, lam = math.radians(lat), math.radians(lon)
        s, c = math.sin(phi), math.cos(phi)
        t = math.tan(phi) ** 2
        cc = self.ep2 * c * c
        a = (lam - self.lon0) * c
        nu = self.a / math.sqrt(1 - self.e2 * s * s)
        ep2 = self.ep2
        e = self.fe + self.k0 * nu * (a + (1 - t + cc) * a ** 3 / 6
                                      + (5 - 18 * t + t * t + 72 * cc - 58 * ep2) * a ** 5 / 120)
        n = self.fn + self.k0 * (self._m(phi) - self.m0 + nu * math.tan(phi) * (
            a * a / 2 + (5 - t + 9 * cc + 4 * cc * cc) * a ** 4 / 24
            + (61 - 58 * t + t * t + 600 * cc - 330 * ep2) * a ** 6 / 720))
        return e, n


def osgb_example():
    """EPSG Guidance Note 7-2's worked TM example (OSGB 1936 / British
    National Grid), used to test the formulas."""
    return TransverseMercator(-2, 49, 0.9996012717, 400000.0, -100000.0, AIRY_1830,
                              reference=(0.5, 50.5, 577274.99, 69740.50), name="EPSG:27700 (example)")
