package com.roboverify.platform.auth;

import cn.dev33.satoken.stp.StpUtil;
import org.springframework.stereotype.Component;

@Component
public class SaTokenOperatorProvider implements OperatorProvider {

    @Override
    public String current() {
        return String.valueOf(StpUtil.getLoginId());
    }
}
