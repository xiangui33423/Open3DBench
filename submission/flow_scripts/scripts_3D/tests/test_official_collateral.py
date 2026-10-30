"""Unused official macros must remain in the submitted ODB library set."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
import run_router


class OfficialCollateralTest(unittest.TestCase):
    def test_configuration_retains_unused_libraries_and_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / 'case'
            platform = root / 'platform'
            (case / 'grt_input').mkdir(parents=True)
            (case / 'flow_design').mkdir()
            platform.mkdir()
            design = case / 'grt_input/4_1_cts.def'
            design.write_text('COMPONENTS 1 ;\n- inst USED ;\nEND COMPONENTS\n')
            (case / 'flow_design/config.mk').write_text(
                'ADDITIONAL_LEFS = $(PLATFORM_DIR)/unused.lef\n'
                'ADDITIONAL_LIBS = $(PLATFORM_DIR)/unused.lib\n')
            (platform / 'config.mk').write_text(
                'TECH_LEF = $(PLATFORM_DIR)/tech.lef\n'
                'SC_LEF = $(PLATFORM_DIR)/cells.lef\n'
                'LIB_FILES = $(PLATFORM_DIR)/cells.lib $(ADDITIONAL_LIBS)\n')
            for name, content in {'tech.lef': '', 'cells.lef': 'MACRO USED\n',
                                  'unused.lef': 'MACRO UNUSED\n', 'cells.lib': '',
                                  'unused.lib': ''}.items():
                (platform / name).write_text(content)
            lefs, libs = run_router.select_collateral(design, platform)
            self.assertEqual([p.name for p in lefs], ['tech.lef', 'cells.lef', 'unused.lef'])
            self.assertEqual([p.name for p in libs], ['cells.lib', 'unused.lib'])

    def test_missing_configuration_fails_instead_of_dropping_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(FileNotFoundError, 'official design configuration'):
                run_router.select_collateral(root / 'grt_input/4_1_cts.def', root)


if __name__ == '__main__':
    unittest.main()
