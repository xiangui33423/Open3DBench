# Optional GRT_PREPARE_TCL hook. Export the loaded OpenDB design, plan metal
# layer sharing in Python, and apply the resulting OpenDB edits once. The
# caller persists the shared ODB/DEF used by both die routing processes.
namespace eval mls_prepare {
  variable script_dir [file dirname [file normalize [info script]]]

  proc json_string {value} {
    set escaped [string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t \b \\b \f \\f] $value]
    # Instance/net names can contain Tcl metacharacters and control characters.
    # JSON encoding must preserve their literal spelling without evaluation.
    set result ""
    foreach ch [split $escaped ""] {
      scan $ch %c code
      if {$code < 32} {
        append result [format {\u%04x} $code]
      } else {
        append result $ch
      }
    }
    return \"$result\"
  }

  proc hbt_name {name} {
    return [expr {[string match HBT_* $name] || [string match LS_HBT_* $name]}]
  }

  proc instance_die {inst} {
    foreach name [list [$inst getName] [[$inst getMaster] getName]] {
      if {[string match *_bottom $name]} { return bottom }
      if {[string match *_upper $name]} { return upper }
    }
    return ""
  }

  proc layer_die {layer} {
    if {$layer ne "NULL" && [regexp {^metal([0-9]+)$} [$layer getName] -> number]} {
      if {$number <= 10} { return bottom }
      return upper
    }
    return ""
  }

  proc json_die {die} {
    if {$die eq ""} { return null }
    return [json_string $die]
  }

  proc rect_values {rect} {
    return [list [$rect xMin] [$rect yMin] [$rect xMax] [$rect yMax]]
  }

  proc inst_snapshot {block} {
    set snapshot [dict create]
    foreach inst [$block getInsts] {
      set name [$inst getName]
      if {[hbt_name $name]} { continue }
      dict set snapshot $name [list [[$inst getMaster] getName] \
        [$inst getOrigin] [$inst getOrient] [$inst getPlacementStatus]]
    }
    return $snapshot
  }

  proc bterm_snapshot {block} {
    set snapshot [dict create]
    foreach bterm [$block getBTerms] {
      set net [$bterm getNet]
      set net_name ""
      if {$net ne "NULL"} { set net_name [$net getName] }
      set geometry {}
      foreach bpin [$bterm getBPins] {
        set boxes {}
        foreach box [$bpin getBoxes] {
          lappend boxes [list [[$box getTechLayer] getName] \
            [rect_values $box]]
        }
        lappend geometry [list [$bpin getPlacementStatus] $boxes]
      }
      dict set snapshot [$bterm getName] [list [$bterm getIoType] \
        [$bterm getSigType] $net_name $geometry]
    }
    return $snapshot
  }

  proc check_snapshot {before after what} {
    if {[dict size $before] != [dict size $after]} {
      error "MLS preparation changed the number of $what"
    }
    dict for {name value} $before {
      if {![dict exists $after $name] || [dict get $after $name] ne $value} {
        error "MLS preparation changed protected $what '$name'"
      }
    }
  }

  proc check_hbt_master {db name} {
    set master [$db findMaster $name]
    if {$master eq "NULL"} { error "MLS requires HBT master '$name'" }
    foreach {pin expected_layer} {BOT metal10 TOP metal11} {
      set mterm [$master findMTerm $pin]
      if {$mterm eq "NULL"} { error "$name is missing terminal $pin" }
      set found 0
      foreach mpin [$mterm getMPins] {
        foreach box [$mpin getGeometry] {
          set layer [$box getTechLayer]
          if {$layer ne "NULL" && [$layer getName] eq $expected_layer} { set found 1 }
        }
      }
      if {!$found} { error "$name/$pin has no geometry on $expected_layer" }
    }
    return $master
  }

  proc iterm_record {iterm} {
    set inst [$iterm getInst]
    set name [$inst getName]
    set pin [[$iterm getMTerm] getName]
    set is_hbt [hbt_name $name]
    set die [instance_die $inst]
    if {$is_hbt} {
      if {$pin eq "BOT"} { set die bottom }
      if {$pin eq "TOP"} { set die upper }
    }
    lassign [$iterm getAvgXY] valid x y
    if {!$valid} {
      set box [$inst getBBox]
      set x [expr {([$box xMin] + [$box xMax]) / 2}]
      set y [expr {([$box yMin] + [$box yMax]) / 2}]
    }
    set hbt_json [expr {$is_hbt ? "true" : "false"}]
    return [format {{"inst":%s,"pin":%s,"x":%d,"y":%d,"die":%s,"io":%s,"hbt":%s}} \
      [json_string $name] [json_string $pin] $x $y [json_die $die] \
      [json_string [$iterm getIoType]] $hbt_json]
  }

  proc bterm_record {bterm} {
    set count 0
    set sx 0
    set sy 0
    set dies {}
    foreach bpin [$bterm getBPins] {
      foreach box [$bpin getBoxes] {
        set rect $box
        incr sx [expr {([$rect xMin] + [$rect xMax]) / 2}]
        incr sy [expr {([$rect yMin] + [$rect yMax]) / 2}]
        incr count
        set die [layer_die [$box getTechLayer]]
        if {$die ne "" && [lsearch -exact $dies $die] < 0} { lappend dies $die }
      }
    }
    set die ""
    if {[llength $dies] == 1} { set die [lindex $dies 0] }
    set x [expr {$count ? $sx / $count : 0}]
    set y [expr {$count ? $sy / $count : 0}]
    return [format {{"inst":"PIN","pin":%s,"x":%d,"y":%d,"die":%s,"io":%s,"hbt":false}} \
      [json_string [$bterm getName]] $x $y [json_die $die] \
      [json_string [$bterm getIoType]]]
  }

  proc export_manifest {path db block bottom_master} {
    set dbu [$block getDbUnitsPerMicron]
    set grid [[ord::get_db_tech] getManufacturingGrid]
    if {$grid < 1} { set grid 1 }
    set area [rect_values [$block getDieArea]]
    set fp [open $path w]
    puts -nonewline $fp "\{"
    puts $fp [format {"dbu_per_micron":%d,"manufacturing_grid":%d,"die_area":[%s],"hbt_master_size":[%d,%d],"hbts":[} \
      $dbu $grid [join $area ,] [$bottom_master getWidth] [$bottom_master getHeight]]
    set sep ""
    foreach inst [$block getInsts] {
      set name [$inst getName]
      if {![hbt_name $name]} { continue }
      set box [$inst getBBox]
      set x [expr {([$box xMin] + [$box xMax]) / 2}]
      set y [expr {([$box yMin] + [$box yMax]) / 2}]
      puts $fp "$sep[format {{"name":%s,"x":%d,"y":%d}} [json_string $name] $x $y]"
      set sep ,
    }
    puts $fp {],"nets":[}
    set sep ""
    foreach net [$block getNets] {
      set pins {}
      foreach iterm [$net getITerms] { lappend pins [iterm_record $iterm] }
      set bterms [$net getBTerms]
      foreach bterm $bterms { lappend pins [bterm_record $bterm] }
      set special [expr {[$net isSpecial] ? "true" : "false"}]
      set has_bterms [expr {[llength $bterms] ? "true" : "false"}]
      puts $fp "$sep[format {{"name":%s,"signal_type":%s,"special":%s,"bterms":%s,"pins":[%s]}} \
        [json_string [$net getName]] [json_string [$net getSigType]] \
        $special $has_bterms [join $pins ,]]"
      set sep ,
    }
    puts $fp "\]\}"
    close $fp
  }

  proc run {} {
    variable script_dir
    set db [ord::get_db]
    set block [ord::get_db_block]
    if {$block eq "NULL"} { error "MLS preparation requires a loaded design" }
    set bot_master [check_hbt_master $db HBT_BOTIN]
    set top_master [check_hbt_master $db HBT_TOPIN]
    if {[$bot_master getWidth] != [$top_master getWidth] || \
        [$bot_master getHeight] != [$top_master getHeight]} {
      error "MLS HBT masters must have equal dimensions"
    }
    set original_instances [inst_snapshot $block]
    set original_bterms [bterm_snapshot $block]
    set manifest $::env(RESULTS_DIR)/mls_manifest.json
    set plan $::env(RESULTS_DIR)/mls_plan.json
    set apply_tcl $::env(RESULTS_DIR)/mls_apply.tcl
    export_manifest $manifest $db $block $bot_master
    set command [list python3 $script_dir/mls_planner.py --manifest $manifest \
      --plan $plan --apply-tcl $apply_tcl]
    if {[info exists ::env(MLS_CONFIG)] && $::env(MLS_CONFIG) ne ""} {
      lappend command --config [file normalize $::env(MLS_CONFIG)]
    }
    if {[info exists ::env(MLS_TIMING_CSV)] && $::env(MLS_TIMING_CSV) ne ""} {
      lappend command --timing-csv [file normalize $::env(MLS_TIMING_CSV)]
    }
    puts "MLS geometry manifest: $manifest"
    puts [exec {*}$command 2>@1]
    # Execute at global scope so the emitted script uses the usual OpenROAD
    # Tcl context, while all integration helpers remain in this namespace.
    uplevel #0 [list source $apply_tcl]
    check_snapshot $original_instances [inst_snapshot $block] "non-HBT components"
    check_snapshot $original_bterms [bterm_snapshot $block] "package pins"
    puts "MLS preparation preserved [dict size $original_instances] components and [dict size $original_bterms] package pins; plan: $plan"
  }
}

mls_prepare::run
