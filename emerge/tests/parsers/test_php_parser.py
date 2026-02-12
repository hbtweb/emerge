"""
All unit tests that are related to PHPParser.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

from typing import Dict
import unittest

from tests.testdata.php import PHP_TEST_FILES

from emerge.languages.phpparser import PHPParser
from emerge.results import FileResult, EntityResult
from emerge.languages.abstractparser import LanguageType
from emerge.analysis import Analysis


class PHPParserTestCase(unittest.TestCase):

    def setUp(self):
        self.example_data = PHP_TEST_FILES
        self.parser = PHPParser()
        self.analysis = Analysis()
        self.analysis.analysis_name = "test"
        self.analysis.source_directory = "/tests"

    def tearDown(self):
        pass

    def test_generate_file_results(self):
        """Generate file results for all parsers and check if metrics were calculated."""
        self.assertFalse(self.parser.results)

        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        results: Dict[str, FileResult] = self.parser.results
        self.assertTrue(results)
        self.assertTrue(len(results) == 8)  # 8 PHP test files

        result: FileResult
        for _, result in results.items():
            self.assertTrue(len(result.scanned_tokens) > 0)

            self.assertTrue(result.analysis.analysis_name.strip())
            self.assertTrue(result.scanned_file_name.strip())
            self.assertTrue(result.scanned_by.strip())
            self.assertTrue(result.scanned_language == LanguageType.PHP)

    def test_generate_file_results_with_imports(self):
        """Generate file results and verify imports are extracted."""
        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        results: Dict[str, FileResult] = self.parser.results

        # Check UserRepository.php has imports
        user_repo_results = [r for r in results.values() if r.scanned_file_name == "UserRepository.php"]
        self.assertTrue(len(user_repo_results) == 1)
        user_repo = user_repo_results[0]
        self.assertTrue(len(user_repo.scanned_import_dependencies) > 0)
        # Should have imports like PDO, App\Models\User, etc.
        import_names = [dep.split('\\')[-1] for dep in user_repo.scanned_import_dependencies]
        self.assertIn('PDO', import_names)
        self.assertIn('User', import_names)

    def test_namespace_extraction(self):
        """Verify namespaces are correctly extracted."""
        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        results: Dict[str, FileResult] = self.parser.results

        # Check that namespaces are extracted
        user_results = [r for r in results.values() if r.scanned_file_name == "User.php"]
        self.assertTrue(len(user_results) == 1)
        user = user_results[0]
        self.assertEqual(user.module_name, "App\\Models")

        # Check UserService namespace
        service_results = [r for r in results.values() if r.scanned_file_name == "UserService.php"]
        self.assertTrue(len(service_results) == 1)
        service = service_results[0]
        self.assertEqual(service.module_name, "App\\Services")

    def test_generate_entity_results(self):
        """Generate entity results and check basic attributes."""
        self.assertFalse(self.parser.results)

        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        results: Dict[str, EntityResult] = self.parser.results
        self.assertTrue(results)
        self.assertTrue(len(results) == 8)  # 8 file results

        self.parser.generate_entity_results_from_analysis(self.analysis)
        self.analysis.collect_results_from_parser(self.parser)
        entity_results = self.analysis.entity_results

        # Should have entities: UserRepository, UserService, User, AbstractController,
        # UserController, RepositoryInterface, CacheableTrait, AdminUser
        self.assertTrue(len(entity_results) >= 8)

        result: EntityResult
        for _, result in entity_results.items():
            self.assertTrue(len(result.scanned_tokens) > 0)
            self.assertTrue(result.analysis.analysis_name.strip())
            self.assertTrue(result.entity_name.strip())
            self.assertTrue(result.scanned_file_name.strip())
            self.assertTrue(result.scanned_by.strip())
            self.assertTrue(result.scanned_language == LanguageType.PHP)

    def test_inheritance_extraction(self):
        """Verify inheritance relationships are extracted."""
        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        self.parser.generate_entity_results_from_analysis(self.analysis)
        self.analysis.collect_results_from_parser(self.parser)
        entity_results = self.analysis.entity_results

        # UserController extends AbstractController
        user_controller_results = [r for r in entity_results.values() if r.entity_name == "UserController"]
        self.assertTrue(len(user_controller_results) == 1)
        user_controller = user_controller_results[0]
        self.assertIn("AbstractController", user_controller.scanned_inheritance_dependencies)

        # AdminUser extends User
        admin_results = [r for r in entity_results.values() if r.entity_name == "AdminUser"]
        self.assertTrue(len(admin_results) == 1)
        admin = admin_results[0]
        self.assertIn("User", admin.scanned_inheritance_dependencies)

    def test_unique_entity_names(self):
        """Verify unique entity names include namespace."""
        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        self.parser.generate_entity_results_from_analysis(self.analysis)
        self.analysis.collect_results_from_parser(self.parser)
        entity_results = self.analysis.entity_results

        # Check that unique names include namespace
        unique_names = list(entity_results.keys())

        # Should have fully qualified names like App\Models\User
        self.assertTrue(any('App\\Models\\User' in name for name in unique_names))
        self.assertTrue(any('App\\Services\\UserService' in name for name in unique_names))

    def test_interface_detection(self):
        """Verify interfaces are correctly detected."""
        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        self.parser.generate_entity_results_from_analysis(self.analysis)
        self.analysis.collect_results_from_parser(self.parser)
        entity_results = self.analysis.entity_results

        # RepositoryInterface should be detected
        interface_results = [r for r in entity_results.values() if r.entity_name == "RepositoryInterface"]
        self.assertTrue(len(interface_results) == 1)

    def test_trait_detection(self):
        """Verify traits are correctly detected."""
        for file_name, file_content in self.example_data.items():
            self.parser.generate_file_result_from_analysis(self.analysis, file_name=file_name, full_file_path="/tests/" + file_name, file_content=file_content)

        self.parser.generate_entity_results_from_analysis(self.analysis)
        self.analysis.collect_results_from_parser(self.parser)
        entity_results = self.analysis.entity_results

        # CacheableTrait should be detected
        trait_results = [r for r in entity_results.values() if r.entity_name == "CacheableTrait"]
        self.assertTrue(len(trait_results) == 1)


if __name__ == '__main__':
    unittest.main()
