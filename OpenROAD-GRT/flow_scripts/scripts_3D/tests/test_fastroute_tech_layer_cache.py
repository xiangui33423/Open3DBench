#!/usr/bin/env python3
"""Compile the real FastRoute cache/resistance functions against small ODB stubs.

Only dependency objects are stubbed: the six production method bodies are
extracted unchanged from utility.cpp. FASTROUTE_UTILITY_CPP can point to an old
source file to demonstrate that the regression tests detect the original bug.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[4]
UTILITY_CPP = Path(os.environ.get(
    "FASTROUTE_UTILITY_CPP",
    REPOSITORY / "OpenROAD-GRT/openroad_src/src/grt/src/fastroute/src/utility.cpp",
))


def production_function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for offset in range(opening + 1, len(source)):
        depth += (source[offset] == "{") - (source[offset] == "}")
        if not depth:
            return source[start:offset + 1]
    raise ValueError(f"Unterminated function: {signature}")


STUBS = r'''
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
constexpr float BIG_INT = 1000000000;

namespace odb {
struct dbTechLayer {
  int level;
  double resistance;
  dbTechLayer* upper = nullptr;
  dbTechLayer* getUpperLayer() { return upper; }
  int getWidth() { return 1; }
  double getResistance() { return resistance; }
};
struct dbTech {
  std::array<dbTechLayer, 20> metals;
  std::array<dbTechLayer, 20> cuts;
  explicit dbTech(double scale = 1) {
    for (int i = 0; i < 20; ++i) {
      cuts[i] = {i + 1, scale * (i + 1) * 100, nullptr};
      metals[i] = {i + 1, scale * (i + 1) * 10, &cuts[i]};
    }
  }
  dbTechLayer* findRoutingLayer(int level) { return &metals.at(level - 1); }
};
struct dbDatabase {
  dbTech* tech;
  dbTech* getTech() { return tech; }
};
struct dbTechLayerRule { int getWidth() { return 1; } };
struct dbTechNonDefaultRule {
  dbTechLayerRule rule;
  dbTechLayerRule* getLayerRule(dbTechLayer*) { return &rule; }
};
struct dbNet { dbTechNonDefaultRule* getNonDefaultRule() { return nullptr; } };
}

struct FrNet {
  odb::dbNet net;
  odb::dbNet* getDbNet() { return &net; }
  int getMinLayer() { return 0; }
  int getMaxLayer() { return 19; }
};

class FastRouteCore {
 public:
  odb::dbDatabase* db_;
  int num_layers_ = 0;
  bool resistance_aware_ = false;
  std::vector<odb::dbTechLayer*> db_layers_;
  void preProcessTechLayers();
  odb::dbTechLayer* getTechLayer(int layer, bool is_via);
  float dbuToMicrons(int length) { return length; }
  float getWireResistance(int layer, int length, FrNet* net);
  int getWireCost(int layer, int length, FrNet* net);
  float getViaResistance(int from_layer, int to_layer);
  int getViaCost(int from_layer, int to_layer);
};
'''

HARNESS = r'''
void require(bool condition, const std::string& message) {
  if (!condition) { throw std::runtime_error(message); }
}

void checkMapping(FastRouteCore& router, odb::dbTech& tech) {
  for (int layer = 0; layer < router.num_layers_; ++layer) {
    auto* metal = router.getTechLayer(layer, false);
    auto* cut = router.getTechLayer(layer, true);
    require(metal == &tech.metals[layer],
            "routing index " + std::to_string(layer) + " expected metal"
                + std::to_string(layer + 1) + " got metal"
                + std::to_string(metal->level));
    require(cut == &tech.cuts[layer], "wrong via at index " + std::to_string(layer));
  }
  require(router.db_layers_.size() == static_cast<size_t>(2 * router.num_layers_),
          "cache retains entries from previous pass");
}

int main(int argc, char** argv) {
  try {
    require(argc == 2, "expected scenario argument");
    const std::string scenario = argv[1];
    odb::dbTech tech;
    odb::dbDatabase db{&tech};
    FastRouteCore router;
    router.db_ = &db;
    if (scenario == "ra_off") {
      // An empty cache and null net make any accidental RA access fail.
      require(router.getWireCost(100, 10, nullptr) == 0, "RA-off wire cost changed");
      require(router.getViaCost(100, 102) == 0, "RA-off via cost changed");
    } else if (scenario == "first_pass") {
      router.num_layers_ = 10;
      router.preProcessTechLayers();
      checkMapping(router, tech);
    } else if (scenario == "10_to_20" || scenario == "resistance") {
      router.num_layers_ = 10;
      router.preProcessTechLayers();
      router.num_layers_ = 20;
      router.preProcessTechLayers();
      if (scenario == "10_to_20") {
        checkMapping(router, tech);
      } else {
        FrNet net;
        router.resistance_aware_ = true;
        require(router.getWireResistance(10, 5, &net) == 550,
                "second-pass metal11 wire resistance used a stale layer");
        require(router.getWireCost(10, 5, &net) == 55,
                "second-pass wire cost used a stale layer");
        require(router.getViaResistance(10, 13) == 3600,
                "second-pass via11..13 resistance used stale layers");
        require(router.getViaCost(10, 13) == 36,
                "second-pass via cost used stale layers");
      }
    } else if (scenario == "shrink" || scenario == "repeat") {
      router.num_layers_ = 20;
      router.preProcessTechLayers();
      router.num_layers_ = scenario == "shrink" ? 10 : 20;
      router.preProcessTechLayers();
      checkMapping(router, tech);
    } else if (scenario == "new_technology") {
      router.num_layers_ = 10;
      router.preProcessTechLayers();
      odb::dbTech other_tech(2);
      db.tech = &other_tech;
      router.preProcessTechLayers();
      checkMapping(router, other_tech);
    } else {
      throw std::runtime_error("unknown scenario");
    }
    std::cout << "PASS " << scenario << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
'''


@unittest.skipUnless(shutil.which("c++"), "C++ compiler is not installed")
class FastRouteTechLayerCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = UTILITY_CPP.read_text()
        signatures = (
            "void FastRouteCore::preProcessTechLayers()",
            "odb::dbTechLayer* FastRouteCore::getTechLayer(",
            "float FastRouteCore::getWireResistance(",
            "int FastRouteCore::getWireCost(",
            "float FastRouteCore::getViaResistance(",
            "int FastRouteCore::getViaCost(",
        )
        actual_functions = "\n\n".join(production_function(source, item) for item in signatures)
        program = directory / "regression.cpp"
        program.write_text(STUBS + actual_functions + HARNESS)
        cls.binary = directory / "regression"
        result = subprocess.run(
            ["c++", "-std=c++17", "-O0", "-Wall", "-Wextra", "-Werror",
             str(program), "-o", str(cls.binary)], capture_output=True, text=True,
            check=False, timeout=30,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"PASS {scenario}\n")

    def test_first_pass_maps_all_metals_and_cuts(self):
        self.run_scenario("first_pass")

    def test_bottom_to_upper_pass_rebuilds_all_twenty_layers(self):
        self.run_scenario("10_to_20")

    def test_second_pass_wire_and_via_resistance_use_correct_layers(self):
        self.run_scenario("resistance")

    def test_fewer_layers_discard_old_tail(self):
        self.run_scenario("shrink")

    def test_same_layer_count_does_not_accumulate_entries(self):
        self.run_scenario("repeat")

    def test_technology_replacement_does_not_retain_old_pointers(self):
        self.run_scenario("new_technology")

    def test_ra_off_costs_do_not_read_cache(self):
        self.run_scenario("ra_off")


if __name__ == "__main__":
    unittest.main()
