package com.roboverify.platform.common.api;

import com.roboverify.platform.common.web.TraceIdFilter;

/**
 * 统一返回包装。所有 REST 接口返回此结构，禁止裸返回 DTO。
 */
public record Result<T>(int code, String message, T data, String traceId) {

    public static <T> Result<T> ok(T data) {
        return new Result<>(ErrorCode.OK.getCode(), ErrorCode.OK.getMessage(), data, currentTraceId());
    }

    public static Result<Void> ok() {
        return ok(null);
    }

    public static <T> Result<T> fail(ErrorCode errorCode) {
        return new Result<>(errorCode.getCode(), errorCode.getMessage(), null, currentTraceId());
    }

    public static <T> Result<T> fail(ErrorCode errorCode, String detail) {
        return new Result<>(errorCode.getCode(), detail, null, currentTraceId());
    }

    private static String currentTraceId() {
        String traceId = org.slf4j.MDC.get(TraceIdFilter.TRACE_ID_KEY);
        return traceId != null ? traceId : "";
    }
}
