# Keep the isolated-process implementation available for exact comparisons.
set grt_process_mode [expr {[info exists ::env(GRT_PROCESS_MODE)] ? $::env(GRT_PROCESS_MODE) : "single"}]
switch -- $grt_process_mode {
  single {
    source [file join $::env(SCRIPTS_DIR) ../scripts_3D/global_route_single_process.tcl]
  }
  isolated {
    source [file join $::env(SCRIPTS_DIR) ../scripts_3D/global_route_die_by_die.tcl]
  }
  default {
    error "GRT_PROCESS_MODE must be 'single' or 'isolated'"
  }
}

# This is a complete replacement for the stock global-route step.  Exit the
# OpenROAD process cleanly so the stock single-pass commands do not run.
exit 0
