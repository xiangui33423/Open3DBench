#!/usr/bin/env python3
"""Execute production C++ methods and Tcl wrappers for explicit RA selection."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_fastroute_tech_layer_cache import REPOSITORY, production_function

GRT = REPOSITORY / "OpenROAD-GRT/openroad_src/src/grt"

STUBS = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
constexpr int GRT = 0;
namespace odb {
enum class dbSigType { SIGNAL, CLOCK };
struct dbNet { void* getNonDefaultRule() { return nullptr; } };
}
namespace sta { constexpr float INF = 1e30f; }
struct Logger {
  bool debugCheck(int, const char*, int) { return false; }
  template <class... T> void report(T...) {}
  template <class... T> void error(int, int id, T...) {
    throw std::runtime_error(std::to_string(id));
  }
};
struct Network {
  int reads = 0;
  void* defaultLibertyLibrary() { ++reads; return this; }
};
struct Sta {
  Network network;
  Network* getDbNetwork() { return &network; }
};
struct Callback {
  int calls = 0;
  void triggerOnEstimateParasiticsRequired() { ++calls; }
};
struct FrNet {
  odb::dbNet dbnet;
  bool clock = false, selected = false;
  float slack = -1, resistance = 1;
  int length = 100;
  bool isClock() { return clock; }
  bool isResAware() { return selected; }
  void setIsResAware(bool value) { selected = value; }
  odb::dbNet* getDbNet() { return &dbnet; }
  float getSlack() { return slack; }
  void setSlack(float value) { slack = value; }
  void setResistance(float value) { resistance = value; }
  float getResistance() { return resistance; }
  void setNetLength(int value) { length = value; }
  int getNetLength() { return length; }
  int getNumPins() { return 2; }
  const char* getName() { return "net"; }
  void addPin(int, int, int) {}
};
struct TreeNode { int16_t x = 0; };
struct TreeEdge { int len = 0, n1 = 0; };
struct StTree {
  std::vector<TreeNode> nodes{{0}, {10}};
  std::vector<TreeEdge> edges{{10, 0}};
  int num_terminals = 2;
  int num_edges() const { return edges.size(); }
};
struct OrderNetPin {
  int treeIndex, minX;
  float length_per_pin;
  int ndr_priority;
  float res_aware_score;
  int clock;
};
struct RoutePt {
  int x() { return 0; }
  int y() { return 0; }
  int layer() { return 1; }
};
struct Net {
  FrNet* net;
  odb::dbNet* getDbNet() { return net->getDbNet(); }
  odb::dbSigType getSignalType() {
    return net->clock ? odb::dbSigType::CLOCK : odb::dbSigType::SIGNAL;
  }
  bool isLocal() { return false; }
  float getSlack() { return -1; }
  bool areSegmentsRestored() { return false; }
};
class FastRouteCore {
 public:
  bool enable_resistance_aware_ = false, selective_resistance_aware_ = false;
  bool resistance_aware_ = false, en_estimate_parasitics_ = false;
  bool is_incremental_grt_ = false, is_3d_step_ = false;
  int score_calls = 0, slack_calls = 0;
  Sta* sta_;
  Callback* callback_handler_;
  Logger* logger_;
  std::vector<int> net_ids_{0, 1, 2};
  std::vector<FrNet*> nets_;
  std::vector<StTree> sttrees_{3};
  std::vector<OrderNetPin> tree_order_pv_;
  void setResistanceAware(bool resistance_aware, bool selective = false);
  void updateSlacks(float percentage);
  void netpinOrderInc();
  float getResAwareScore(FrNet*) { ++score_calls; return 1; }
  float getNetSlack(odb::dbNet*) { ++slack_calls; return -1; }
  float getNetResistance(FrNet*, bool = false) { return 1; }
  void resetWorstMetrics() {}
  void updateWorstMetrics(FrNet*) {}
  template <class... T> FrNet* addNet(odb::dbNet* dbnet, T...) {
    for (auto* net : nets_) { if (net->getDbNet() == dbnet) { return net; } }
    throw std::runtime_error("unknown net");
  }
  bool hasSaveSttInput() { return false; }
  odb::dbNet* getDebugNet() { return nullptr; }
};
class GlobalRouter {
 public:
  bool resistance_aware_ = false;
  std::set<odb::dbNet*> resistance_aware_nets_;
  FastRouteCore* fastroute_;
  Logger* logger_;
  void setNetResistanceAware(odb::dbNet*);
  void clearNetResistanceAware();
  void configResistanceAware();
  void makeFastrouteNet(Net*);
  void findFastRoutePins(Net*, std::vector<RoutePt>& pins, int& root) {
    pins.emplace_back(); root = 0;
  }
  void computeTrackConsumption(Net*, int8_t& cost, std::vector<int8_t>*& layer) {
    cost = 1; layer = nullptr;
  }
  void getNetLayerRange(odb::dbNet*, int& low, int& high) { low = 1; high = 10; }
  bool getNetRoutingLayerRange(odb::dbNet*, int& low, int& high) {
    low = 1; high = 10; return true;
  }
  void saveSttInputFile(Net*) {}
};
'''

HARNESS = r'''
void require(bool condition, const std::string& message) {
  if (!condition) { throw std::runtime_error(message); }
}
int main(int argc, char** argv) {
  try {
    require(argc == 2, "expected scenario");
    const std::string scenario = argv[1];
    Logger logger;
    Sta sta;
    Callback callback;
    FrNet selected, ordinary, clock;
    clock.clock = true;
    FastRouteCore core;
    core.sta_ = &sta;
    core.logger_ = &logger;
    core.callback_handler_ = &callback;
    core.nets_ = {&selected, &ordinary, &clock};
    core.sttrees_[0].edges[0].len = 20;
    core.sttrees_[1].edges[0].len = 10;
    core.sttrees_[2].edges[0].len = 30;
    GlobalRouter router;
    router.fastroute_ = &core;
    router.logger_ = &logger;
    if (scenario == "selective") {
      router.setNetResistanceAware(selected.getDbNet());
      router.setNetResistanceAware(selected.getDbNet());
      require(router.resistance_aware_nets_.size() == 1, "duplicate selection");
      // The DB can be marked CLOCK by STA after the caller selected its name.
      router.setNetResistanceAware(clock.getDbNet());
      router.configResistanceAware();
      for (auto* net : core.nets_) { Net wrapper{net}; router.makeFastrouteNet(&wrapper); }
      require(selected.selected && !ordinary.selected && !clock.selected,
              "selection affected another signal or clock");
      core.updateSlacks(0.15);
      core.netpinOrderInc();
      require(sta.network.reads == 0 && callback.calls == 0 && core.slack_calls == 0,
              "selective mode accessed STA or parasitics");
      require(core.score_calls == 0, "selective mode used unnormalized score");
      require(core.tree_order_pv_[0].treeIndex == 1
                  && core.tree_order_pv_[1].treeIndex == 0
                  && core.tree_order_pv_[2].treeIndex == 2,
              "selective mode changed baseline length-per-pin order");
    } else if (scenario == "reset") {
      router.setNetResistanceAware(selected.getDbNet());
      router.configResistanceAware();
      selected.selected = true;
      core.resistance_aware_ = true;
      router.clearNetResistanceAware();
      router.configResistanceAware();
      require(!core.enable_resistance_aware_ && !core.selective_resistance_aware_
                  && !core.resistance_aware_, "RA state leaked to next die");
      Net wrapper{&selected};
      router.makeFastrouteNet(&wrapper);
      require(!selected.selected, "reused net retained manual RA flag");
    } else if (scenario == "auto") {
      router.resistance_aware_ = true;
      router.configResistanceAware();
      require(core.enable_resistance_aware_ && !core.selective_resistance_aware_
                  && core.en_estimate_parasitics_, "native auto mode disabled");
      core.updateSlacks(1.0);
      require(sta.network.reads == 1 && callback.calls == 1 && core.slack_calls == 3,
              "native auto mode bypassed STA");
      require(selected.selected && ordinary.selected && clock.selected,
              "native auto selection changed");
      core.netpinOrderInc();
      require(core.tree_order_pv_[0].treeIndex == 2 && core.score_calls > 0,
              "native auto clock/score priorities changed");
      Net wrapper{&selected};
      router.makeFastrouteNet(&wrapper);
      require(selected.selected, "native automatic selection reset on net import");
    } else if (scenario == "conflict" || scenario == "null") {
      try {
        if (scenario == "conflict") {
          router.setNetResistanceAware(selected.getDbNet());
          router.resistance_aware_ = true;
          router.configResistanceAware();
        } else { router.setNetResistanceAware(nullptr); }
      } catch (const std::runtime_error& error) {
        require(std::string(error.what()) == (scenario == "conflict" ? "725" : "724"),
                "wrong validation failure");
        std::cout << "PASS " << scenario << '\n';
        return 0;
      }
      throw std::runtime_error("invalid configuration accepted");
    } else { throw std::runtime_error("unknown scenario"); }
    std::cout << "PASS " << scenario << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
'''


@unittest.skipUnless(shutil.which("c++"), "C++ compiler is not installed")
class SelectiveResistanceAwareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        functions = []
        for path, signatures in [
            ("src/fastroute/src/utility.cpp", ["static bool compareNetPins(",
             "void FastRouteCore::netpinOrderInc()", "void FastRouteCore::updateSlacks("]),
            ("src/fastroute/src/FastRoute.cpp", ["void FastRouteCore::setResistanceAware("]),
            ("src/GlobalRouter.cpp", ["void GlobalRouter::setNetResistanceAware(",
             "void GlobalRouter::clearNetResistanceAware()", "void GlobalRouter::configResistanceAware()",
             "void GlobalRouter::makeFastrouteNet("]),
        ]:
            source = (GRT / path).read_text()
            functions.extend(production_function(source, item) for item in signatures)
        program = directory / "selective.cpp"
        program.write_text(STUBS + "\n\n".join(functions) + HARNESS)
        cls.binary = directory / "selective"
        result = subprocess.run(["c++", "-std=c++20", "-O0", "-Wall", "-Wextra", "-Werror",
                                 str(program), "-o", str(cls.binary)],
                                capture_output=True, text=True, check=False, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def invoke(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"PASS {scenario}\n")

    def test_only_selected_signal_uses_ra_without_sta_or_clock_priority(self):
        self.invoke("selective")

    def test_clear_and_next_pass_disable_manual_ra_and_stale_flags(self):
        self.invoke("reset")

    def test_native_auto_mode_retains_sta_selection_and_clock_priority(self):
        self.invoke("auto")

    def test_native_and_manual_modes_conflict(self):
        self.invoke("conflict")

    def test_null_net_is_rejected(self):
        self.invoke("null")


@unittest.skipUnless(shutil.which("tclsh"), "Tcl is not installed")
class SelectiveResistanceAwareTclTest(unittest.TestCase):
    def invoke(self, action):
        source = (GRT / "src/GlobalRouter.tcl").read_text()
        start = source.index('sta::define_cmd_args "set_net_resistance_aware"')
        stop = source.index('sta::define_cmd_args "set_nets_to_route"', start)
        stubs = r'''
namespace eval sta {
  proc define_cmd_args {args} {}
  proc parse_key_args {args} {}
  proc check_argc_eq1 {name argv} {if {[llength $argv] != 1} {error "arity"}}
  proc check_argc_eq0 {name argv} {if {[llength $argv] != 0} {error "arity"}}
}
namespace eval ord {proc get_db_block {} {return $::block}}
namespace eval utl {proc error {area code text} {::error "$code $text"}}
namespace eval grt {
  proc set_net_resistance_aware {net} {puts "SELECT $net"}
  proc clear_net_resistance_aware {} {puts CLEAR}
}
proc dbblock {method name} {
  if {$name eq {signal[0]}} {return NET}
  return NULL
}
set block dbblock
'''
        return subprocess.run(["tclsh"], input=stubs + source[start:stop]
                              + "\nif {[catch {\n" + action
                              + "\n} message]} {puts stderr $message; exit 1}\n",
                              capture_output=True, text=True, check=False, timeout=5)

    def test_exact_bus_name_and_clear_reach_native_api(self):
        result = self.invoke("set_net_resistance_aware {signal[0]}\nclear_net_resistance_aware")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "SELECT NET\nCLEAR\n")

    def test_invalid_net_block_and_arity_fail_before_native_selection(self):
        for action, error in [("set_net_resistance_aware missing", "727"),
                              ("set block NULL\nset_net_resistance_aware net", "726"),
                              ("set_net_resistance_aware one two", "arity"),
                              ("clear_net_resistance_aware extra", "arity")]:
            with self.subTest(action=action):
                result = self.invoke(action)
                self.assertEqual(result.returncode, 1)
                self.assertIn(error, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
