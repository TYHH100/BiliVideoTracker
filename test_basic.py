#!/usr/bin/env python3
"""
基本测试文件，用于GitHub Actions工作流
"""

import os
import sys
import unittest

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestBasicImports(unittest.TestCase):
    """Test basic import functionality"""
    
    def test_app_import(self):
        """Test app module import"""
        try:
            import app
            self.assertTrue(hasattr(app, 'app'))
            print("✓ app module imported successfully")
        except ImportError as e:
            self.fail(f"app module import failed: {e}")
    
    def test_core_modules_import(self):
        """Test core modules import"""
        modules = ['bili_api', 'database', 'logger', 'notifier', 'scheduler']
        
        for module_name in modules:
            try:
                module = __import__(f'core.{module_name}', fromlist=[module_name])
                self.assertIsNotNone(module)
                print(f"✓ core.{module_name} module imported successfully")
            except ImportError as e:
                self.fail(f"core.{module_name} module import failed: {e}")
    
    def test_flask_app_creation(self):
        """Test Flask app creation"""
        try:
            from app import app
            self.assertTrue(hasattr(app, 'test_client'))
            print("✓ Flask app created successfully")
        except Exception as e:
            self.fail(f"Flask app creation failed: {e}")

class TestFunctionality(unittest.TestCase):
    """Test basic functionality"""
    
    def test_database_module(self):
        """Test database module"""
        try:
            import core.database as db
            # Check for basic database functions
            self.assertTrue(hasattr(db, 'init_dbs'))
            self.assertTrue(hasattr(db, 'SQLiteConnectionPool'))
            print("✓ Database module functions correctly")
        except Exception as e:
            self.fail(f"Database module test failed: {e}")
    
    def test_bili_api_module(self):
        """Test BiliAPI module"""
        try:
            from core.bili_api import BiliAPI
            api = BiliAPI()
            self.assertIsNotNone(api)
            print("✓ BiliAPI module functions correctly")
        except Exception as e:
            self.fail(f"BiliAPI module test failed: {e}")


def run_tests():
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestBasicImports))
    suite.addTests(loader.loadTestsFromTestCase(TestFunctionality))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 返回测试结果
    return result.wasSuccessful()

if __name__ == '__main__':
    # 设置编码以支持中文字符
    import io
    import sys
    
    # 对于Windows环境，设置标准输出的编码
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("Running BiliVideoTracker basic tests...")
    print("=" * 50)
    
    success = run_tests()
    
    print("=" * 50)
    if success:
        print("✓ All tests passed!")
        sys.exit(0)
    else:
        print("✗ Some tests failed!")
        sys.exit(1)
