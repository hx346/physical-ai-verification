package com.roboverify.platform.common.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.roboverify.platform.storage.StorageProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(StorageProperties.class)
public class PropertiesConfig {

    /**
     * Jackson 2 ObjectMapper（业务 IR 处理与 Sa-Token 使用）。
     * Boot 4.1 的 starter-jackson 默认装配 Jackson 3（tools.jackson.*，供 HTTP 层），
     * 两代包名不同可并存；此处显式提供 Jackson 2 bean 供注入。
     */
    @Bean
    public ObjectMapper jackson2ObjectMapper() {
        return new ObjectMapper()
                .registerModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    }
}
