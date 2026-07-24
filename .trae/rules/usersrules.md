---
alwaysApply: false
description: 
---
// 用户权限等级定义（从高到低）
const USER_ROLES = {
  HARDWARE_ADMIN: '硬件管理员',  // 最高权限：硬件管理相关操作
  SUPER_ADMIN: '超级管理员',      // 系统级超级权限
  ADMIN: '管理员',                // 普通管理员权限
  NORMAL_USER: '普通用户'         // 包含学生、设计师等普通用户
};

// 权限等级数值（数值越大权限越高）
const PERMISSION_LEVELS = {
  [USER_ROLES.HARDWARE_ADMIN]: 100,
  [USER_ROLES.SUPER_ADMIN]: 80,
  [USER_ROLES.ADMIN]: 60,
  [USER_ROLES.NORMAL_USER]: 20
};

// 权限比较函数
function hasPermission(userRole, requiredRole) {
  const userLevel = PERMISSION_LEVELS[userRole] || 0;
  const requiredLevel = PERMISSION_LEVELS[requiredRole] || 0;
  return userLevel >= requiredLevel;
}

// 权限检查装饰器
function requirePermission(minimumRole) {
  return function(target, propertyKey, descriptor) {
    const originalMethod = descriptor.value;
    descriptor.value = function(...args) {
      const currentUser = this.getCurrentUser?.() || global.currentUser;
      if (!hasPermission(currentUser?.role, minimumRole)) {
        throw new Error(`权限不足：需要 ${minimumRole} 或以上权限`);
      }
      return originalMethod.apply(this, args);
    };
    return descriptor;
  };
}
