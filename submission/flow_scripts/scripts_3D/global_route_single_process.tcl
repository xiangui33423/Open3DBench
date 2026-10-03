# Two-pass GRT in one OpenROAD process. Both passes keep their
# original die-only layer interval. read_guides resets the queued net subset;
# temporary net flags limit that reset to bottom pins and are restored at once.
utl::set_metrics_stage "globalroute__fused"
source $::env(SCRIPTS_DIR)/load.tcl
load_design 4_cts.odb 4_cts.sdc "Starting fused die-by-die global routing"
set fused_script_dir [file dirname [file normalize [info script]]]
set fused_input_def $::env(RESULTS_DIR)/4_1_cts.def
if {[info exists ::env(GRT_PREPARE_TCL)] && $::env(GRT_PREPARE_TCL) ne ""} {
  source [file normalize $::env(GRT_PREPARE_TCL)]
  set fused_input_def $::env(RESULTS_DIR)/4_grt_input.def
  write_db $::env(RESULTS_DIR)/4_grt_input.odb
  write_def $fused_input_def
}
set ::env(GRT_INPUT_DEF) $fused_input_def
# Keep the pre-GRT metadata used by an isolated finalizer. make_tracks appends
# patterns to a populated grid, and GRT marks clock leaf nets as CLOCK.
set fused_block [ord::get_db_block]
set fused_net_sigtypes {}
foreach net [$fused_block getNets] { lappend fused_net_sigtypes [list $net [$net getSigType]] }
set fused_track_patterns {}
set fused_layer_adjustments {}
foreach layer [[ord::get_db_tech] getLayers] {
  if {[$layer getType] ne "ROUTING"} { continue }
  lappend fused_layer_adjustments [list $layer [$layer getLayerAdjustment]]
  set track [$fused_block findTrackGrid $layer]
  set x_patterns {}
  set y_patterns {}
  set existed [expr {$track ne "NULL"}]
  if {$existed} {
    for {set i 0} {$i < [$track getNumGridPatternsX]} {incr i} {
      lappend x_patterns [$track getGridPatternX $i]
    }
    for {set i 0} {$i < [$track getNumGridPatternsY]} {incr i} {
      lappend y_patterns [$track getGridPatternY $i]
    }
  }
  lappend fused_track_patterns [list $layer $existed $x_patterns $y_patterns]
}
if {[info exists ::env(FASTROUTE_TCL)]} { source $::env(FASTROUTE_TCL) }
if {[info commands set_net_routing_layers] eq ""} {
  error "Fused routing requires hard per-net routing layer constraints"
}
set fused_bot_min [expr {[info exists ::env(BOTTOM_DIE_MIN_LAYER)] ? $::env(BOTTOM_DIE_MIN_LAYER) : "metal2"}]
set fused_bot_max [expr {[info exists ::env(BOTTOM_DIE_MAX_LAYER)] ? $::env(BOTTOM_DIE_MAX_LAYER) : "metal10"}]
set fused_top_min [expr {[info exists ::env(UPPER_DIE_MIN_LAYER)] ? $::env(UPPER_DIE_MIN_LAYER) : "metal11"}]
set fused_top_max [expr {[info exists ::env(UPPER_DIE_MAX_LAYER)] ? $::env(UPPER_DIE_MAX_LAYER) : "metal20"}]
set fused_adjustment [expr {[info exists ::env(GLOBAL_ROUTING_LAYER_ADJUSTMENT)] ? $::env(GLOBAL_ROUTING_LAYER_ADJUSTMENT) : 0.5}]
set fused_args [expr {[info exists ::env(GLOBAL_ROUTE_ARGS)] ? $::env(GLOBAL_ROUTE_ARGS) : \
  {-allow_congestion -congestion_iterations 1 -congestion_report_iter_step 5 -verbose}}]
set fused_list_dir $::env(RESULTS_DIR)/die_net_lists
exec python3 $fused_script_dir/export_die_net_lists.py $fused_input_def $fused_list_dir
set fused_block [ord::get_db_block]
proc fused_read_nets {path} {
  set fp [open $path r]
  set names {}
  foreach name [split [read $fp] "\n"] {
    set name [string trim $name]
    if {$name ne ""} { lappend names $name }
  }
  close $fp
  return $names
}
proc fused_route_pass {names min_layer max_layer guide report} {
  # An empty GRT queue means all nets in OpenROAD. Publish an empty pass
  # without calling the router when this die has no routable net.
  if {[llength $names] == 0} {
    set fp [open $guide w]
    close $fp
    set fp [open $report w]
    close $fp
    return
  }
  set_routing_layers -signal ${min_layer}-${max_layer}
  set_global_routing_layer_adjustment ${min_layer}-${max_layer} $::fused_adjustment
  if {[info exists ::env(MACRO_EXTENSION)]} { set_macro_extension $::env(MACRO_EXTENSION) }
  foreach name $names {
    set net [$::fused_block findNet $name]
    if {$net eq "NULL"} { error "Missing classified net '$name'" }
    set_net_routing_layers $name $min_layer $max_layer
    grt::add_net_to_route $net
  }
  puts "Fused process pass: [llength $names] nets on $min_layer-$max_layer"
  global_route -guide_file $guide -congestion_report_file $report {*}$::fused_args
}
set fused_bottom [fused_read_nets $fused_list_dir/bottom_2d.txt]
set fused_upper [fused_read_nets $fused_list_dir/upper_2d.txt]
set fused_bottom_guide $::env(RESULTS_DIR)/route_bottom.guide
set fused_upper_guide $::env(RESULTS_DIR)/route_upper.guide
fused_route_pass $fused_bottom $fused_bot_min $fused_bot_max \
  $fused_bottom_guide $::env(REPORTS_DIR)/congestion_bottom.rpt

# read_guides clears nets_to_route_ without reloading the design or Liberty.
# Only bottom nets may rebuild pin models on the current bottom-only grid.
# The other nets' original special flags are restored before upper routing.
set fused_bottom_set [dict create]
foreach name $fused_bottom { dict set fused_bottom_set $name 1 }
set fused_temporary_flags {}
foreach net [$fused_block getNets] {
  if {![dict exists $fused_bottom_set [$net getName]] && ![$net isSpecial]} {
    lappend fused_temporary_flags $net
    $net setSpecial
  }
}
try {
  if {[llength $fused_bottom]} { read_guides $fused_bottom_guide }
} finally {
  foreach net $fused_temporary_flags { $net clearSpecial }
}
# A stock write_guides emits all guides stored in OpenDB. Remove the first
# pass's stored guides after its immutable guide file has been saved, so the
# upper output contains exactly the upper pass like an isolated process.
foreach net [$fused_block getNets] {
  foreach guide [$net getGuides] { odb::dbGuide_destroy $guide }
}
fused_route_pass $fused_upper $fused_top_min $fused_top_max \
  $fused_upper_guide $::env(REPORTS_DIR)/congestion_upper.rpt

set fused_guide $::env(RESULTS_DIR)/route.guide
exec python3 $fused_script_dir/merge_route_guides.py $fused_guide $fused_bottom_guide $fused_upper_guide
if {![info exists ::env(VALIDATE_DIE_GUIDES)] || $::env(VALIDATE_DIE_GUIDES) ni {"" "0"}} {
  set fused_max_cc [expr {[info exists ::env(DIE_GUIDE_MAX_CC_RECTS)] ? $::env(DIE_GUIDE_MAX_CC_RECTS) : 5000}]
  exec python3 $fused_script_dir/check_2d_net_guide_layers.py $fused_guide $fused_input_def
  exec python3 $fused_script_dir/diagnose_guide_connectivity.py $::env(RESULTS_DIR) \
    --def-file $fused_input_def --strict --top 50 --max-cc-rects $fused_max_cc
}
# Restore exactly the track patterns and net uses saved before routing. Native
# OpenROAD cannot read_db over a populated design, so restoration uses OpenDB
# setters and recreates each grid immediately to retain its original table id.
foreach entry $fused_track_patterns {
  lassign $entry layer existed x_patterns y_patterns
  set track [$fused_block findTrackGrid $layer]
  if {$track ne "NULL"} { odb::dbTrackGrid_destroy $track }
  if {$existed} {
    set track [odb::dbTrackGrid_create $fused_block $layer]
    foreach pattern $x_patterns { $track addGridPatternX {*}$pattern }
    foreach pattern $y_patterns { $track addGridPatternY {*}$pattern }
  }
}
foreach entry $fused_net_sigtypes {
  lassign $entry net sigtype
  if {[$net getSigType] ne $sigtype} { $net setSigType $sigtype }
}
grt::clear_net_routing_layers
set_routing_layers -signal ${fused_bot_min}-${fused_top_max}
read_guides $fused_guide
# Capacity adjustments are router settings. Keep the prepared database values
# in the published ODB, as a fresh isolated finalizer does.
foreach entry $fused_layer_adjustments {
  lassign $entry layer adjustment
  $layer setLayerAdjustment $adjustment
}
# The fixed evaluator reads the original SDC and extracts its own parasitics.
# Publishing the routed ODB does not require a separate STA/ref-clock pass.
set fused_output $::env(RESULTS_DIR)/5_1_grt.odb
write_db $fused_output
set fused_marker $::env(RESULTS_DIR)/.grt_finalize_complete
set fp [open ${fused_marker}.[pid].tmp w]
puts $fp "odb_size=[file size $fused_output]"
close $fp
file rename -force ${fused_marker}.[pid].tmp $fused_marker
puts "Fused die-by-die GRT complete: $fused_output"
