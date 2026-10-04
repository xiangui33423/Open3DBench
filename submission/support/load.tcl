set_thread_count $::env(NUM_CORES)
source [file join [file dirname [info script]] sdc_compat.tcl]
source $::env(SUBMISSION_COLLATERAL_TCL)
proc load_design {design_file sdc_file msg} {
  if {[info commands set_net_routing_layers] eq ""} {
    error "Required set_net_routing_layers is unavailable; compile the submitted GRT overlay with build.sh"
  }
  puts "SUBMISSION_LAYER_CLAMP_READY"
  foreach lib $::submission_libs { read_liberty $lib }
  if {[file extension $design_file] eq ".def"} {
    foreach lef $::submission_lefs { read_lef $lef }
    read_def $::env(RESULTS_DIR)/$design_file
  } else {
    read_db $::env(RESULTS_DIR)/$design_file
  }
  read_sdc_compat $::env(RESULTS_DIR)/$sdc_file
  if {[file exists $::env(PLATFORM_DIR)/derate.tcl]} {
    source $::env(PLATFORM_DIR)/derate.tcl
  }
  source $::env(PLATFORM_DIR)/setRC.tcl
}
