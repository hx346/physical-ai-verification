package com.roboverify.platform.common.config;

import com.roboverify.platform.storage.StorageProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(StorageProperties.class)
public class PropertiesConfig {
}
