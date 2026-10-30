# Resolve the same complete collateral list as the official evaluator.
include $(DESIGN_CONFIG)
include $(PLATFORM_DIR)/config.mk

.PHONY: collateral
collateral:
	@test -n "$(TECH_LEF)" -a -n "$(SC_LEF)" -a -n "$(LIB_FILES)"
	@printf 'LEF\t%s\n' $(foreach path,$(TECH_LEF) $(SC_LEF) $(ADDITIONAL_LEFS),"$(path)")
	@printf 'LIB\t%s\n' $(foreach path,$(LIB_FILES),"$(path)")
