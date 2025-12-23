#!/usr/bin/env python3
"""
基本测试文件，用于GitHub Actions工作流
"""

import unittest
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class TestBasicImports(unittest.TestCase):
    """测试基本导入功能"""
    
    def test_app_import(self):
        """测试app模块导入"""
        try:
            import app
            self.assertTrue(hasattr(app, 'app'))
            print("✓ app模块导入成功")
        except ImportError as e:
            self.fail(f"app模块导入失败: {e}")
    
    def test_core_modules_import(self):
        """测试core模块导入"""
        modules = ['bili_api', 'database', 'logger', 'notifier', 'scheduler']
        
        for module_name in modules:
            try:
                module = __import__(f'core.{module_name}', fromlist=[module_name])
                self.assertIsNotNone(module)
                print(f"✓ core.{module_name}模块导入成功")
            except ImportError as e:
                self.fail(f"core.{module_name}模块导入失败: {e}")
    
    def test_flask_app_creation(self):
        """测试Flask应用创建"""
        try:
            from app import app
            self.assertTrue(hasattr(app, 'test_client'))
            print("✓ Flask应用创建成功")
        except Exception as e:
            self.fail(f"Flask应用创建失败: {e}")

class TestFunctionality(unittest.TestCase):
    """测试基本功能"""
    
    def test_database_module(self):
        """测试数据库模块"""
        try:
            import core.database as db
            # 检查是否有基本的数据库函数
            self.assertTrue(hasattr(db, 'init_db'))
            print("✓ 数据库模块功能正常")
        except Exception as e:
            self.fail(f"数据库模块测试失败: {e}")
    
    def test_bili_api_module(self):
        """测试BiliAPI模块"""
        try:
            from core.bili_api import BiliAPI
            api = BiliAPI()
            self.assertIsNotNone(api)
            print("✓ BiliAPI模块功能正常")
        except Exception as e:
            self.fail(f"BiliAPI模块测试失败: {e}")

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
    print("运行BiliVideoTracker基本测试...")
    print("=" * 50)
    
    success = run_tests()
    
    print("=" * 50)
    if success:
        print("✓ 所有测试通过!")
        sys.exit(0)
    else:
        print("✗ 部分测试失败!")
        sys.exit(1)