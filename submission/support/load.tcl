set_thread_count $::env(NUM_CORES)
source [file join [file dirname [info script]] sdc_compat.tcl]
source $::env(SUBMISSION_COLLATERAL_TCL)
proc load_design {design_file sdc_file msg} {
  foreach lib $::submission_libs { read_liberty $lib }
  read_db $::env(RESULTS_DIR)/$design_file
  read_sdc_compat $::env(RESULTS_DIR)/$sdc_file
  if {[file exists $::env(PLATFORM_DIR)/derate.tcl]} {
    source $::env(PLATFORM_DIR)/derate.tcl
  }
  source $::env(PLATFORM_DIR)/setRC.tcl
}
