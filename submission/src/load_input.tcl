set_thread_count $::env(NUM_CORES)
source $::env(SUBMISSION_COLLATERAL_TCL)
foreach lef $submission_lefs { read_lef $lef }
read_def $::env(RESULTS_DIR)/4_1_cts.def
write_db $::env(RESULTS_DIR)/4_cts.odb
