package com.roboverify.platform.common.config;

import cn.dev33.satoken.interceptor.SaInterceptor;
import cn.dev33.satoken.stp.StpUtil;
import com.roboverify.platform.common.web.TraceIdFilter;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 层配置：traceId 过滤器（最先执行）+ Sa-Token 登录拦截。
 * 白名单：登录接口与 actuator（健康检查）。
 */
@Configuration
public class WebConfig {

    private static final int TRACE_FILTER_ORDER = 1;

    @Bean
    public FilterRegistrationBean<TraceIdFilter> traceIdFilter() {
        FilterRegistrationBean<TraceIdFilter> registration = new FilterRegistrationBean<>(new TraceIdFilter());
        registration.addUrlPatterns("/*");
        registration.setOrder(TRACE_FILTER_ORDER);
        return registration;
    }

    @Bean
    public WebMvcConfigurer saTokenInterceptor() {
        return new WebMvcConfigurer() {
            @Override
            public void addInterceptors(InterceptorRegistry registry) {
                registry.addInterceptor(new SaInterceptor(handle -> StpUtil.checkLogin()))
                        .addPathPatterns("/api/**")
                        .excludePathPatterns("/api/auth/login");
            }
        };
    }
}
