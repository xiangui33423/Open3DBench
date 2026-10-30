"""Independent exhaustive oracle for the lazy legal-site ordering."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mls_planner import HbtSites


def exhaustive(sites, target, radius, extra=(), limit=8):
    if not sites.nx or not sites.ny:
        return []
    ix = max(0, min(sites.nx - 1, round((target[0] - sites.x0) / sites.step)))
    iy = max(0, min(sites.ny - 1, round((target[1] - sites.y0) / sites.step)))
    points = [(sites.x0 + x * sites.step, sites.y0 + y * sites.step)
              for x in range(max(0, ix-radius), min(sites.nx, ix+radius+1))
              for y in range(max(0, iy-radius), min(sites.ny, iy+radius+1))]
    points.sort(key=lambda p: (abs(p[0]-target[0])+abs(p[1]-target[1]), p))
    available = [p for p in points if sites.legal(p, extra)]
    return available[:max(1, limit)]


class LazyHbtSitesTest(unittest.TestCase):
    def test_exact_order_across_occupied_windows_and_temporary_sites(self):
        rng = random.Random(21018)
        for trial in range(300):
            pitch = rng.choice([20, 100, 6400])
            nx, ny = rng.randrange(1, 25), rng.randrange(1, 25)
            x0, y0 = -10*pitch, -5*pitch
            occupied = [dict(x=x0+rng.randrange(nx)*pitch+10,
                             y=y0+rng.randrange(ny)*pitch+10)
                        for _ in range(rng.randrange(nx*ny//2+1))]
            sites = HbtSites([x0,y0,x0+nx*pitch+20,y0+ny*pitch+20], [20,20], pitch, 10, occupied)
            target = (rng.uniform(x0-pitch,x0+(nx+1)*pitch), rng.uniform(y0-pitch,y0+(ny+1)*pitch))
            radius, limit = rng.randrange(-1, 12), rng.choice([-1,0,1,8,16])
            extra = [(x0+pitch+5, y0+2*pitch+11)]
            with self.subTest(trial=trial):
                self.assertEqual(sites.nearby(target,radius,extra,limit), exhaustive(sites,target,radius,extra,limit))

    def test_distance_ties_keep_grid_order(self):
        sites = HbtSites([0,0,620,620], [20,20], 100, 10, [])
        self.assertEqual(sites.nearby((260,260),3,limit=4), [(210,210),(210,310),(310,210),(310,310)])

    def test_fully_blocked_and_empty_lattices(self):
        occupied = [dict(x=x,y=y) for x in (10,110,210) for y in (10,110,210)]
        sites = HbtSites([0,0,220,220],[20,20],100,10,occupied)
        self.assertEqual(sites.nearby((110,110),4), [])
        empty = HbtSites([0,0,10,10],[20,20],100,10,[])
        self.assertEqual(empty.nearby((0,0),4), [])


if __name__ == '__main__':
    unittest.main()
