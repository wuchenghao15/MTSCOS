"""
文案中枢管理系统 (Copy Hub Management System, CHMS)
服务包初始化

模块:
  - copy_asset_service: 文案资产存储引擎 (CHMS-01)
  - copy_feature_mapper: 文案-功能关联引擎 (CHMS-03)
"""
from services.copy_hub.copy_asset_service import CopyAssetService
from services.copy_hub.copy_feature_mapper import CopyFeatureMapper

__all__ = ['CopyAssetService', 'CopyFeatureMapper']
__version__ = '1.0.0'
