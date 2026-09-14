package com.roboverify.platform.common.exception;

import com.roboverify.platform.common.api.ErrorCode;

/**
 * 业务异常：可预期错误，全局异常处理器统一转 Result，不打堆栈。
 * 系统级错误直接抛原始异常（全局处理器打堆栈）。
 */
public class BizException extends RuntimeException {

    private final ErrorCode errorCode;

    public BizException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }

    public BizException(ErrorCode errorCode, String detail) {
        super(detail);
        this.errorCode = errorCode;
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
