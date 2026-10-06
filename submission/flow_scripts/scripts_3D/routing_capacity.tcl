# Optional per-layer routing resource reductions. These are router settings;
# they do not change tracks, physical technology rules, or net layer windows.
namespace eval grt_capacity {}

proc grt_capacity::parse {spec} {
  set overrides [dict create]
  if {[string trim $spec] eq ""} { return $overrides }
  set tech [ord::get_db_tech]
  foreach entry [split $spec ,] {
    if {![regexp {^\s*([^\s=,]+)\s*=\s*([^\s=,]+)\s*$} $entry -> name value]} {
      error "GRT_LAYER_ADJUSTMENTS requires comma-separated layer=value entries"
    }
    # Decimal syntax excludes Tcl expressions, hexadecimal, NaN, and infinity.
    if {![regexp {^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$} $value]
        || ![string is double -strict $value]
        || [catch {expr {double($value)}} adjustment]
        || !($adjustment >= 0.0 && $adjustment <= 1.0)} {
      error "GRT_LAYER_ADJUSTMENTS value for '$name' must be finite and in \[0,1\]"
    }
    set layer [$tech findLayer $name]
    if {$layer eq "NULL" || [$layer getType] ne "ROUTING"} {
      error "GRT_LAYER_ADJUSTMENTS unknown routing layer '$name' (use individual layer names)"
    }
    set level [$layer getRoutingLevel]
    if {[dict exists $overrides $level]} {
      error "GRT_LAYER_ADJUSTMENTS repeats routing layer '$name'"
    }
    dict set overrides $level [list [$layer getName] $adjustment]
  }
  return $overrides
}

proc grt_capacity::apply {min_layer max_layer} {
  if {![info exists ::env(GRT_LAYER_ADJUSTMENTS)]
      || [string trim $::env(GRT_LAYER_ADJUSTMENTS)] eq ""} { return }
  # Validate the complete specification before applying any overrides. Valid
  # entries for the other die are retained in the input and skipped this pass.
  set overrides [grt_capacity::parse $::env(GRT_LAYER_ADJUSTMENTS)]
  set tech [ord::get_db_tech]
  set lo [$tech findLayer $min_layer]
  set hi [$tech findLayer $max_layer]
  if {$lo eq "NULL" || $hi eq "NULL"
      || [$lo getType] ne "ROUTING" || [$hi getType] ne "ROUTING"
      || [$lo getRoutingLevel] > [$hi getRoutingLevel]} {
    error "Invalid routing capacity die window '$min_layer-$max_layer'"
  }
  set first [$lo getRoutingLevel]
  set last [$hi getRoutingLevel]
  foreach level [lsort -integer [dict keys $overrides]] {
    if {$level < $first || $level > $last} { continue }
    lassign [dict get $overrides $level] name adjustment
    # Called after the uniform setting and the active routing window, so this
    # replaces that layer's reduction rather than multiplying reductions.
    set_global_routing_layer_adjustment $name $adjustment
    puts "GRT_CAPACITY layer=$name adjustment=[format %.12g $adjustment] die=$min_layer-$max_layer"
  }
}
