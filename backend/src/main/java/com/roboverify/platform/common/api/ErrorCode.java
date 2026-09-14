package com.roboverify.platform.common.api;

/**
 * 平台错误码。分段：0 成功；1xxx 通用；2xxx 鉴权；3xxx 业务域。
 */
public enum ErrorCode {

    OK(0, "ok"),

    BAD_REQUEST(1000, "请求参数不合法"),
    INTERNAL_ERROR(1500, "系统内部错误"),

    UNAUTHORIZED(2001, "未登录或凭证已失效"),
    FORBIDDEN(2003, "无权限"),
    USERNAME_OR_PASSWORD_ERROR(2004, "用户名或密码错误"),

    PROJECT_NOT_FOUND(3001, "项目不存在"),
    JOB_NOT_FOUND(3002, "任务不存在"),
    RUNTIME_UNAVAILABLE(3500, "工程运行时不可用");

    private final int code;
    private final String message;

    ErrorCode(int code, String message) {
        this.code = code;
        this.message = message;
    }

    public int getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }
}
