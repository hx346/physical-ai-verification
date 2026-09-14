package com.roboverify.platform.auth;

/**
 * 当前操作者来源抽象：生产环境取 Sa-Token 会话；测试环境可注入固定值。
 */
public interface OperatorProvider {

    String current();
}
